# Ubuntu 24.04 release-package journey

Run this on a real Ubuntu 24.04 x64 desktop in a dedicated test account. FUSE and a screenshot
tool (`gnome-screenshot`, `scrot`, or ImageMagick `import`) must be available.

```bash
frontends/desktop/e2e/linux/Invoke-LinuxUserJourney.sh \
  --artifact /path/GenericAgent-Desktop-Linux-Portable.tar.gz \
  --expected-commit <candidate-sha> \
  --keep-work-dir
```

The wrapper verifies/extracts the tar, preserves the AppImage launch path, and runs the shared
production journey. The journey covers package shape, embedded Python, first launch, warm
restart, package-owned bridge plus external `GA_ROOT`, deterministic chat, upload, memory import,
foreign-port protection, recovery after release, relocation into a path containing spaces and
Chinese characters, stale-override fallback, optional P2P degradation, screenshots, and cleanup.

After automation passes, edit `report/real-package-report.json` and mark the Linux manual items
`pass`: executable bit and desktop launcher, window dragging/close behavior, retry button after
port release, native directory picker, and visual/loading checks. P2 evidence is incomplete while
any manual item remains `pending`.
