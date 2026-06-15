# IG-XL 15Q Retrieval Evaluation

Date: 2026-05-28

Scope: IG-XL/J750 documents ingested into the ATE KB vector store.

Method: 15 self-asked questions were sent through the MCP `ate_kb.ask` path with an IG-XL tag filter. Each row records the expected source, actual retrieved source, answer correctness, and whether SMT7/V93000 content was mixed into the answer.

## Summary

| Metric | Result |
| --- | --- |
| Total questions | 15 |
| MCP-first retrieval used | 15 / 15 |
| Correct answers | 9 / 15 |
| Partially correct answers | 2 / 15 |
| Incorrect or insufficient answers | 4 / 15 |
| Mixed SMT7/V93000 content | 0 / 15 |
| Actual sources constrained to IG-XL | 15 / 15 |

## Detailed Results

| # | Question | Expected source_md | Actual source_md | Correct? | Mixed SMT7/V93000? | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | IG-XL/J750 中 license 如何管理？Self Service Licensing portal 在哪里？ | `igxl/igxladmin/adLicensing.2.1.md` | `igxl/igxladmin/adLicensing.2.1.md`; `igxl/relnotescur/ReadMe_V3.60.20.1.07.md`; `igxl/relnotesprev/ReadMe_V3.60.10.2.07.md` | Pass | No | Correctly answered that IG-XL requires licensing, SSL is used for managing licenses, and the portal is `https://teradyne.subscribenet.com`. |
| 2 | J750 Instrument Licensing 中哪些 IG-XL components 需要有效 license file？ | `igxl/igxladmin/adLicensing.2.5.md` | `igxl/igxladmin/adLicensing.2.5.md`; `igxl/testtechniquenotes/ttn_hsd100_hsd200_transition_guide.12.04.md` | Pass | No | Correctly listed DataTool, Bitmap Tool, Redundancy Analysis, RAPlus, Production Bit Map, and SECS/GEM. |
| 3 | APMU 的 V/I features/specifications 在哪里查看？IP750 中 APMU slot assignment 有什么限制？ | `igxl/apmu/apmu_about.1.2.md`; `igxl/hardwarespecs/APMUSpecs.03.01.md`; `igxl/hardwarespecs/APMUSpecs.03.02.md` | `igxl/apmu/APMUDefTopic.md`; `igxl/apmu/apmu_about.1.2.md`; `igxl/hardwarespecs/APMUSpecs.03.01.md`; `igxl/hardwarespecs/APMUSpecs.03.02.md`; `igxl/hardwarespecs/HDAPMUSpecs.08.02.md` | Pass | No | Correctly found APMU feature/spec references and IP750 slot limit: one APMU in fixed slot 5. |
| 4 | DSIO200 的 VSSS/VSSC 是什么？quad mode 是否支持？ | `igxl/patternlanguage/plinstruments.5.07.md`; `igxl/dibdesign/dib_hsd200.16.5.md` | `igxl/dsio200/dsio200prog.3.06.md`; `igxl/dsio200/dsio200prog.3.07.md`; `igxl/dsio200/dsio200prog.3.10.md`; `igxl/dsio800/dsio800_prog.3.10.md`; `igxl/relnotesprev/ReadMe_V3.50.50.4.20.md` | Fail | No | Retrieved quad-mode programming topics but missed the VSSS/VSSC definition and support limitation. An English version of this query previously retrieved the expected source, so this is likely a Chinese query semantic miss. |
| 5 | IG-XL SECS/GEM spooling 在什么 CONTROLSTATE 下有意义？Off-Line 时会发送哪些消息？ | `igxl/secsgem/secs_scenario.11.51.md` | `igxl/datatool/dtribbon.03.10.md`; `igxl/datatool/dtribbon.03.15.md`; `igxl/relnotescur/ReadMe_V3.60.20.1.05.md`; `igxl/relnotesprev/ReadMe_V3.50.50.4.12.md`; `igxl/vbt/hdwDigital.14.218.md` | Fail | No | Missed the SECS/GEM spooling scenario source. Retrieval drifted to general DataTool/notes content. |
| 6 | MTO800 中 Programming the MTO Resource Map 应该查看哪个文档？MTO Pattern Microcodes 应该查看哪个文档？ | `igxl/mto800/mt800prog.3.04.md`; `igxl/patternlanguage/plmto.7.03.md`; `igxl/patterntool/PTVectorsEditing.4.21.md` | `igxl/hardwarespecs/HSD800Specs.14.31.md`; `igxl/mto100/mt100prog.3.4.md`; `igxl/mto200/mtprog.3.4.md`; `igxl/mto800/mt800prog.3.02.md`; `igxl/mto800/mt800prog.3.04.md` | Partial | No | Found the MTO800 resource-map page but did not retrieve the MTO Pattern Microcodes source. |
| 7 | DataTool 中 MTO Resource Map Sheet 的 programming restrictions 和 configuration limitations 应该查看哪里？ | `igxl/datatool/DTSheets.11.185.md`; `igxl/mto800/mt800prog.3.04.md` | `igxl/mto100/mt100prog.3.4.md`; `igxl/mto200/mtprog.3.4.md`; `igxl/mto800/mt800prog.3.04.md` | Partial | No | Retrieved pages that point to the DataTool sheet but missed the direct `DTSheets.11.185.md` source. |
| 8 | Pattern Tool 中如果 pattern file 使用 MTO，Vectors worksheet 会有什么额外内容？ | `igxl/patterntool/PTVectorsEditing.4.21.md`; `igxl/patternlanguage/plmto.7.03.md` | `igxl/hardwarespecs/HSD800Specs.14.31.md`; `igxl/patternlanguage/plmto.7.02.md`; `igxl/patterntool/PTVectorsEditing.4.01.md`; `igxl/patterntool/PTVectorsEditing.4.21.md`; `igxl/relnotescur/ReadMe_V3.60.20.1.17.md` | Pass | No | Correctly identified additional MTO columns in the Vectors worksheet and related MTO microcode/data-generator details. |
| 9 | Test Program Protection Tool 是否保护 Excel .xls/.xlsm workbook？保护 test program 前需要做什么？ | `igxl/tpprotection/TPPUsing.3.5.md`; `igxl/tpprotection/TPPUsing.3.6.md` | `igxl/tpprotection/TPPUsing.3.5.md`; `igxl/tpprotection/TPPUsing.3.6.md` | Pass | No | Correctly answered that Excel `.xls/.xlsm` workbooks are not protected directly and must first be exported to ASCII DataTool files. |
| 10 | IG-XL Test Analysis Tool 如何启动？可以从 Start menu 和 DataTool 哪里进入？ | `igxl/testanalysis/taUsing.1.2.md` | `igxl/datatool/dtworkbook.02.3.md`; `igxl/datatool/dtworkbook.02.8.md`; `igxl/igxladmin/adLicensing.2.5.md`; `igxl/pdf/ip750_users.md`; `igxl/vbt/execExec.33.34.md` | Fail | No | Retrieved DataTool startup/help sources instead of the Test Analysis Tool startup page. |
| 11 | SimulatedConfig_J750.txt 中 slot 0 到 slot 7 配置了哪些 channel、mto、dsio 和 cbrelay 项？ | `igxl/txt/simulatedconfig_j750.md` | `igxl/txt/simulatedconfig_j750.md`; `igxl/txt/simulatedconfig_j750_hdcto.md`; `igxl/txt/simulatedconfig_j750_mso.md` | Pass | No | Correctly found the base simulated configuration; extra variant files are related and did not contaminate the answer. |
| 12 | J750 Visual Basic for Test DriverAPI 的目录中 Hardware Instruments 包含哪些主要对象？ | `igxl/cnt/driverapi.md`; `igxl/cnt/driverapiigxl.md`; `igxl/vbt/usingIntro.02.2.md` | `igxl/cnt/driverapi.md`; `igxl/cnt/driverapiigxl.md`; `igxl/hardwarespecs/HardwareSpecsDefTopic.md`; `igxl/vbt/usingIntro.02.2.md` | Pass | No | Correctly retrieved the DriverAPI TOC sources and summarized Hardware, APMU, BPMU, CTO, DPS, DIB, DSIO, MTO, Pins, Tester, Digital Testing, and related objects. |
| 13 | HSD800 在 J750Ex Instrument Licensing 中有哪些 licensed features？speed 和 LVM licensing 是按什么粒度授权？ | `igxl/igxladmin/adLicensing.2.5.md`; `igxl/igxladmin/adLicensing.2.6.md`; `igxl/igxladmin/adLicensing.2.3.md` | `igxl/igxladmin/adLicensing.2.1.md`; `igxl/igxladmin/adLicensing.2.2.md`; `igxl/igxladmin/adLicensing.2.3.md`; `igxl/igxladmin/adLicensing.2.5.md`; `igxl/igxladmin/adLicensing.2.6.md` | Pass | No | Correctly answered HSD800 licensed features and noted speed/LVM licensing is by 64-channel groups. |
| 14 | Available J750 Features 文档说明 J750 features 按哪些 instrument 或 feature 分类？ | `igxl/igxladmin/adLicensing.2.6.md` | `igxl/datatool/DTRunProg.08.07.md`; `igxl/hardwarespecs/HardwareSpecsDefTopic.md`; `igxl/igxladmin/adLicensing.2.5.md`; `igxl/patterncompiler/pcpatterncompiler.1.6.md` | Fail | No | Missed the direct Available J750 Features source and returned broader licensing/programming pages. |
| 15 | APMU Pins.SpotCalibration 在 VBT 中如何提高精度？它连接什么仪表到 APMU calibration bus？ | `igxl/vbt/hdwAPMU.07.68.md` | `igxl/relnotesprev/ReadMe_V3.60.10.2.17.md`; `igxl/vbt/hdwAPMU.07.68.md`; `igxl/vbt/hdwAPMU.07.70.md` | Pass | No | Correctly found `Pins.SpotCalibration`, including improved force-voltage accuracy and the Agilent 3458 meter connection to the APMU calibration bus. |

## Findings

1. The IG-XL tag filter successfully prevented SMT7/V93000 mixing in this run.
2. Chinese queries worked well for direct title/API/configuration questions, but several scenario-style questions missed the expected source.
3. Retrieval is weaker when the expected answer lives in a specific linked help topic but nearby pointer pages contain similar titles.
4. Some converted help text still has glued tokens from HTML conversion, which may reduce embedding quality for exact phrase queries.

## Recommended Follow-up

1. Save these 15 questions as a regression set, preferably JSONL with expected source patterns and contamination checks.
2. Add query aliases or source hints for weak topics: SECS/GEM spooling, Test Analysis Tool startup, DSIO200 VSSS/VSSC, and Available J750 Features.
3. Improve IG-XL HTML-to-Markdown spacing cleanup for glued identifiers and table text before the next full re-embed.
4. Re-run the same 15 questions after cleanup and compare source hit rate, not only answer text.
