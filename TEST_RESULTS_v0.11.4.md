# 0.11.4 sound audit, full-track listening and ordered workflow

Required test suite is checked locally and again by the release workflow. Windows installation, actual CPU separation/RNNoise, and Tk UI structure are gated before publishing.

- Sound audit distinguishes whole-track processing, observable RMS attenuation, manual mute/fades, cuts and added silence. It never certifies subjective quality or semantic noise removal.
- Cut/speed/insertion mapping splits surviving spans; fully removed spans have no output interval. Undo refreshes TXT/CSV/JSON audit instead of retaining stale mute entries.
- Dedicated optional SRT is checked for valid ordered times within the audio, attached to matching report intervals or neighboring sentences, and tracked as a source file. It does not replace video subtitles or automatically mute subtitle gaps.
- Full-track A/B previews exceed 60 seconds, retain separate revisioned filenames and include the latest original-sound manual edits. Narration denoise preview uses original speed before pause changes.
- Main UI follows five ordered stages; advanced/batch options and logs are moved away from the primary controls. Small screens can scroll.
- Final production reuses a matching reviewed project, preserving manual mutes and enhanced PCM, then applies pause/visual settings. Changed sound settings fail visibly instead of silently dropping edits. A changed output folder receives final deliverables without another encode.
- Original media, sample counts, neural-filter latency compensation, subtitle paging and existing video/cover export are covered by regression tests.

Technical checks do not replace full subjective listening. No automatic semantic noise detector or subtitle/voice content comparison is claimed.
