#!/usr/bin/env node
'use strict';

const crypto = require('node:crypto');
const fs = require('node:fs');
const https = require('node:https');

// --- Argument parsing ---
function parseArgs(argv) {
  const args = {};
  for (let i = 2; i < argv.length; i += 2) {
    const key = argv[i].replace(/^--/, '');
    const val = argv[i + 1];
    if (!val || val.startsWith('--')) {
      console.error(`Missing value for --${key}`);
      process.exit(1);
    }
    args[key] = val;
  }
  return args;
}

const REQUIRED = ['file', 'secret-id', 'secret-key', 'token', 'bucket', 'region', 'cos-key'];

// Default socket timeout: 5 minutes. Override with --timeout <ms>.
// This prevents the Bash tool's hard 120s timeout from silently killing a
// large-file upload mid-stream and leaving a partial COS object.
const DEFAULT_TIMEOUT_MS = 300_000;

// --- Crypto helpers ---
function hmacSha1(key, data) {
  return crypto.createHmac('sha1', key).update(data).digest('hex');
}

function sha1(data) {
  return crypto.createHash('sha1').update(data).digest('hex');
}

// --- COS Authorization header (PUT Object) ---
// Reference: https://cloud.tencent.com/document/product/436/7778
function buildAuthorization({ secretId, secretKey, method, pathname, headers, startTime, expiredTime }) {
  const keyTime = `${startTime};${expiredTime}`;

  // 1. SignKey = HMAC-SHA1(SecretKey, KeyTime)
  const signKey = hmacSha1(secretKey, keyTime);

  // 2. HttpString = method\npathname\nparams\nheaders\n
  // For PUT, no query params; headers we sign: host, content-length
  const headerKeys = Object.keys(headers).sort();
  const httpHeaders = headerKeys.map((k) => `${k.toLowerCase()}=${encodeURIComponent(headers[k])}`).join('&');
  const httpString = `${method.toLowerCase()}\n${pathname}\n\n${httpHeaders}\n`;

  // 3. StringToSign = sha1\nKeyTime\nSHA1(HttpString)\n
  const stringToSign = `sha1\n${keyTime}\n${sha1(httpString)}\n`;

  // 4. Signature = HMAC-SHA1(SignKey, StringToSign)
  const signature = hmacSha1(signKey, stringToSign);

  // 5. Build Authorization
  const headerList = headerKeys.map((k) => k.toLowerCase()).join(';');
  return [
    `q-sign-algorithm=sha1`,
    `q-ak=${secretId}`,
    `q-sign-time=${keyTime}`,
    `q-key-time=${keyTime}`,
    `q-header-list=${headerList}`,
    `q-url-param-list=`,
    `q-signature=${signature}`,
  ].join('&');
}

// --- Upload via PUT Object ---
function upload(args) {
  const secretId = args['secret-id'];
  const secretKey = args['secret-key'];
  const { token } = args;
  const { bucket } = args;
  const { region } = args;
  const cosKey = args['cos-key'];
  const filePath = args.file;

  const startTime = args['start-time'] || String(Math.floor(Date.now() / 1000));
  const expiredTime = args['expired-time'] || String(Math.floor(Date.now() / 1000) + 3600);
  const timeoutMs = parseInt(args.timeout || String(DEFAULT_TIMEOUT_MS), 10);

  const fileContent = fs.readFileSync(filePath);
  const hostname = `${bucket}.cos.${region}.myqcloud.com`;
  const pathname = `/${cosKey}`;

  // Headers to sign
  const signHeaders = {
    'content-length': String(fileContent.length),
    host: hostname,
  };

  const authorization = buildAuthorization({
    secretId,
    secretKey,
    method: 'PUT',
    pathname,
    headers: signHeaders,
    startTime,
    expiredTime,
  });

  // Use the actual file content type if provided, otherwise fall back to octet-stream
  const contentType = args['content-type'] || 'application/octet-stream';

  const options = {
    hostname,
    port: 443,
    path: pathname,
    method: 'PUT',
    headers: {
      'Content-Type': contentType,
      'Content-Length': fileContent.length,
      Authorization: authorization,
      'x-cos-security-token': token,
    },
    timeout: timeoutMs,
  };

  const req = https.request(options, (res) => {
    let body = '';
    res.on('data', (chunk) => (body += chunk));
    res.on('end', () => {
      if (res.statusCode >= 200 && res.statusCode < 300) {
        console.log(`Upload successful (HTTP ${res.statusCode})`);
        process.exit(0);
      } else {
        console.error(`COS upload failed (HTTP ${res.statusCode}): ${body}`);
        process.exit(1);
      }
    });
  });

  req.on('timeout', () => {
    req.destroy();
    console.error(`COS upload timed out after ${timeoutMs}ms. Use --timeout <ms> to extend for large files.`);
    process.exit(1);
  });

  req.on('error', (err) => {
    console.error(`COS upload error: ${err.message}`);
    process.exit(1);
  });

  req.write(fileContent);
  req.end();
}

// --- Main ---
function main() {
  const args = parseArgs(process.argv);

  const missing = REQUIRED.filter((k) => !args[k]);
  if (missing.length) {
    console.error(`Missing required arguments: ${missing.map((k) => `--${k}`).join(', ')}`);
    console.error(
      `Usage: node cos-upload.cjs --file <path> --secret-id <sid> --secret-key <skey> --token <token> --bucket <bucket> --region <region> --cos-key <key> [--content-type <mime>] [--start-time <ts>] [--expired-time <ts>] [--timeout <ms>]`,
    );
    process.exit(1);
  }

  const filePath = args.file;
  if (!fs.existsSync(filePath)) {
    console.error(`File not found: ${filePath}`);
    process.exit(1);
  }

  upload(args);
}

main();
