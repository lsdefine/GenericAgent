# macOS 15 DMG release-package journey

Run this on a real macOS 15 machine in a dedicated test account. The wrapper mounts the DMG,
copies its app into `/Applications` under a collision-safe E2E name, launches the production
binary, and later moves that exact app to a path containing spaces and Chinese characters.

```bash
frontends/desktop/e2e/macos/Invoke-macOSUserJourney.sh \
  --artifact /path/GenericAgent-Desktop-macOS.dmg \
  --expected-commit <candidate-sha> \
  --keep-work-dir
```

In addition to the shared chat/data/port/relocation checks, this journey hard-fails if the DMG
does not contain the build-time `.prepared` marker or if any file inside the `.app` changes from
first launch through restart and relocation. It verifies the package bridge remains inside the
app while `GA_ROOT` points at an external core, then verifies a deleted override falls back to the
versioned writable runtime outside the app.

After automation, mark the manual report items `pass`: Gatekeeper/open-anyway, traffic lights,
focus, retry button after port release, native directory picker, and visual/loading checks. The
wrapper restores the settings file exactly and removes its temporary `/Applications` copy; run it
only in a dedicated account because the normal Application Support runtime may be created.
