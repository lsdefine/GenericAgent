import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';
import fs from 'fs';
import type { Plugin as EsbuildPlugin } from 'esbuild';

/**
 * Prismjs language components are CJS IIFEs that expect a global `Prism`.
 * During esbuild pre-bundling, we inject `var Prism = require("prismjs")`
 * AND the full dependency chain for each component so esbuild creates
 * proper chunk dependency edges (preventing parallel-load race conditions).
 */
function prismjsEsbuildPlugin(): EsbuildPlugin {
  // Dependency map: component name → list of prerequisite components
  const deps: Record<string, string[]> = {
    'prism-markup': [],
    'prism-css': ['prism-markup'],
    'prism-clike': [],
    'prism-javascript': ['prism-clike'],
    'prism-typescript': ['prism-javascript'],
    'prism-jsx': ['prism-markup', 'prism-javascript'],
    'prism-tsx': ['prism-typescript', 'prism-jsx'],
    'prism-c': ['prism-clike'],
    'prism-cpp': ['prism-c'],
    'prism-java': ['prism-clike'],
    'prism-python': [],
    'prism-rust': [],
    'prism-go': ['prism-clike'],
    'prism-bash': [],
    'prism-sql': [],
    'prism-json': [],
    'prism-yaml': [],
    'prism-toml': [],
    'prism-diff': [],
    'prism-markdown': ['prism-markup'],
  };

  return {
    name: 'prismjs-inject-deps',
    setup(build) {
      build.onLoad(
        { filter: /prismjs[\\/]components[\\/]prism-/ },
        async (args) => {
          if (/prism-core/.test(args.path)) return undefined;

          const contents = await fs.promises.readFile(args.path, 'utf8');

          // Determine which component this is
          const match = args.path.match(/prism-([\w-]+?)(?:\.min)?\.js$/);
          const componentName = match ? `prism-${match[1]}` : '';
          const componentDeps = deps[componentName] || [];

          // Build require chain: core first, then deps in order
          const requires = ['var Prism = require("prismjs");'];
          for (const dep of componentDeps) {
            requires.push(`require("prismjs/components/${dep}");`);
          }

          return {
            contents: requires.join('\n') + '\n' + contents,
            loader: 'js',
          };
        }
      );
    },
  };
}

export default defineConfig({
  plugins: [react()],
  server: {
    port: Number(process.env.VITE_PORT || 5173),
    strictPort: true,
  },
  test: {
    environment: 'happy-dom',
    globals: true,
    setupFiles: [],
  },
  build: {
    rollupOptions: {
      input: {
        main: path.resolve(__dirname, 'index.html'),
        loading: path.resolve(__dirname, 'loading.html'),
      },
    },
  },
  optimizeDeps: {
    esbuildOptions: {
      plugins: [prismjsEsbuildPlugin()],
    },
  },
  resolve: {
    alias: {
      '@semi-css': path.resolve(__dirname, 'node_modules/@douyinfe/semi-ui/dist/css/semi.min.css'),
    },
  },
  css: {
    preprocessorOptions: {
      scss: {
        additionalData: '',
      },
    },
  },
});
