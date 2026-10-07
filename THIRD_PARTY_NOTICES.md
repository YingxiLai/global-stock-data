# Third-party components

Original code/Markdown: simonlin1212/global-stock-data, Apache-2.0; retained LICENSE and NOTICE identify provenance and modifications.

Optional protocol SDK: [modelcontextprotocol/python-sdk v2.3.0](https://github.com/modelcontextprotocol/python-sdk/tree/v2.3.0), MIT. Its source is consumed as a pinned dependency, not vendored. The installed wheel includes its license notice. Runtime closure is recorded by uv.lock and hash export; each distribution retains its own licenses.

No EdgarTools, TA-Lib, OpenBB, Financial Datasets or Massive source was copied or installed. Their independent code licenses and data entitlements are documented as candidates in docs/reuse.md.

Build/test tools are pinned development dependencies, not core runtime requirements. Their wheel license notices remain with their distributions. No financial data accompanies any dependency in this repository.
