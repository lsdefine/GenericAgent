# P2 release-package evidence gate

`real_package_journey.py` is the common L5 runner. Platform wrappers install or extract one
artifact produced from a candidate commit and invoke this runner against the production binary.
It temporarily uses the real per-user settings path, restores it byte-for-byte, and therefore
must run in a dedicated Windows/Linux/macOS test account.

Every platform report records the candidate commit, artifact SHA-256, OS/architecture, bootstrap
snapshots, bridge identity/PIDs, package paths before and after relocation, screenshots, redacted
fake-model transcript, data results, cleanup status, and the short manual checklist. Automated
success does not imply P2 completion: testers must change every manual checklist value to `pass`.

After all three reports and the Windows native retry report are complete, combine them:

```bash
python3 frontends/desktop/e2e/package/verify_candidate_evidence.py \
  --expected-commit <candidate-sha> \
  --windows <windows-production-contract-report.json> \
  --linux <linux-real-package-report.json> \
  --macos <macos-real-package-report.json> \
  --windows-native-report <windows-e2e-report.json> \
  --output <candidate-evidence-manifest.json>
```

The verifier fails on a commit mismatch, missing artifact digest, failed automated scenario,
incomplete bootstrap evidence, missing macOS app immutability proof, unfinished manual checklist,
or unclean final process/port state. The manifest is evidence for the candidate SHA; it is not
intended to be committed to the repository.
