# Asset and model licensing

The Apache License 2.0 applies to AptiorDesk's source code and original project assets.
It does not relicense third-party models or stock media.

## Kokoro

The Kokoro-82M model and voice data shipped by AptiorDesk are Apache-2.0
licensed. The `kokoro-onnx` runtime is MIT licensed. The model binaries under
`models/kokoro` use Git LFS so a normal GitHub clone receives the actual
release assets rather than exceeding repository size limits.

Packaged applications also contain libraries under their own licenses,
including Qt/PySide and the phonemizer stack. Release engineering must preserve
their license notices and source-availability obligations.

## Interviewer avatar

The production interviewer is based on the TurboSquid “Cartoon Young Boy
Rigged” asset, product 2429764, distributed under TurboSquid's Standard License.
That license permits use in a larger software creation but does not permit
publishing the underlying 3D model in an open format.

Consequently:

- the GLB and its derived store thumbnail are excluded from this public source
  repository and from the Apache-2.0 license;
- public source checkouts must remain usable without the production avatar;
- release builds obtain the licensed asset from private release storage;
- contributors must not commit the GLB, extracted meshes, textures, converted
  QML geometry, or original archive;
- no public release should be published until the packaged representation has
  been reviewed against the applicable stock-media license.

The original download archives supplied to the project did not contain a
license file. Keep the purchase/download record outside the repository.
