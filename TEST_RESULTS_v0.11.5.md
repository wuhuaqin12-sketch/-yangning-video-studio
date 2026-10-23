# 0.11.5 installer repair

- Interpreter eligibility checks cover Microsoft Store aliases, Store-backed virtual environments with normal-looking executable paths, 32-bit/unsupported versions and ordinary Python paths.
- Missing pyvenv.cfg or a failed interpreter probe is never accepted as an installed runtime.
- Failed application-private environments are renamed for diagnosis before creating a new one. Project/media folders are not touched; live runtimes are not renamed.
- A failed rebuild raises an error rather than proceeding to activation. Healthy runtimes are reused.
- Windows CI now installs through INSTALL.bat --quiet after seeding an incomplete runtime, then verifies the old backup, new config, installed runtime, shortcut, UI and real vocal separation/RNNoise.
- The Store sandbox itself is not reproduced in the hosted Windows runner; path rejection is unit-tested, and repair is tested with a seeded broken environment.

Publishing is gated on the full regression suite and Windows checks.
