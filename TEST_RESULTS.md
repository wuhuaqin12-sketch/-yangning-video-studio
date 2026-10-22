# 0.10.0 validation

22 targeted tests passed in 27.149 seconds, plus Python compilation.

- Actual decoded PCM unchanged by new-project preparation, even when imported old settings request denoise/separation/muting.
- Preparation can skip all audio/video previews; explicit final export succeeds without them.
- Imported legacy jobs have removed audio-processing flags forced off.
- Old processed projects are rejected instead of silently reusing enhanced audio.
- Existing subtitle timing, manual mute/cut/undo, fixed typography, source-backed style/cover export and video-stream copy checks passed.
- Existing workflow states, pause optimization and Japanese 1.1x pitch-preserving output regression checks passed.
- Removed speech-cleaning and separation modules and bundled noise model from this package.
- Main workflow exports directly; optional previews are not prerequisites and final-export confirmation was removed.
- When replacement narration is supplied, the main action uses the existing narration alignment/export pipeline; otherwise it exports the original-sound project directly.

Windows GUI has not been exercised on a physical Windows machine. No full user V11 video was newly exported for this tool update.


0.10.1 regression: 13 tests passed (pixel_aspect_test, workflow_test, no_denoise_test). SAR-tagged synthetic video exports at 4:3, 3:4, 1:1 and near-square ratio; preview, subtitle burn, styled export, cover, original bytes, output geometry and decode checked. Timed UTF-8 TXT parsing verified; untimed TXT rejected. Windows UI and user source video not tested.
