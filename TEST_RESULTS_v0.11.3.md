# 0.11.3 validation

38 required Linux tests passed. Updated deep-profile project export test and seven audio tests passed after the final integration change. Python compilation and git diff whitespace checks passed.

- RNNoise bd model SHA-256 verified against the fixed upstream revision.
- Deep-profile processing preserves sample count and rate for 16k/24k mono and 44.1k/48k stereo, including non-frame-aligned tails. Original files remain byte-identical.
- Final voiced tail remains present; waveform cross-correlation timing differs by less than 1ms on the synthetic changing-pitch test signal. 480 samples at 48k compensate the neural filter buffer; small phase changes from filtering remain possible.
- Missing/corrupted model fails explicitly, without output masquerading as successful denoising.
- Source-backed deep-profile project creates previews/exports with matching duration and subtitle timing.
- Existing typography, subtitle paging, style/cover export, manual mute/cut/undo and desktop updater tests pass.
- This update does not implement semantic noise identification or automatic subtitle alignment. The reference instructions explicitly require listening before muting ambiguous phrase-head sounds. No specific V11 timestamps are applied to new material.
- Windows installation, real CPU vocal separation plus RNNoise, preset UI and instructions window are checked by the release workflow; status must be read from that run before claiming they passed.

Synthetic tests do not certify subjective audio quality or complete removal of overlapping noise. No new full V11 listening review is claimed by this app update.
