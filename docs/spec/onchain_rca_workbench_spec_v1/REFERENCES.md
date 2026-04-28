# References used to prepare this design package

1. MegaETH Aave V3 攻击事件分析报告.pdf
   - Used as the target report-quality reference and golden case.
   - Key aspects: TxAnalyzer + 链上取证工具栈、Step 1–9 分析链路、多签图、攻击时间线/资金流图、数据可靠性。

2. TxAnalyzer 能力评测.pdf
   - Used to define TxAnalyzer as a transaction-level artifact/RCA engine.
   - Key aspects: deterministic artifact pull + AI 6-phase analysis; simplified vs full analysis; benchmark notes.

3. BradMoonUESTC/TxAnalyzer GitHub repository
   - Used to define the CLI integration point, artifact directory convention, supported workflow, and GPL license consideration.
