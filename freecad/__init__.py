"""OrionFlow FreeCAD extraction pipeline.

Deterministic, LLM-free conversion of the gNucleus FreeCAD dataset
(Description + Key Parameters + .FCStd) into FeatureGraph JSON training pairs.

Two interpreters are involved by necessity:
  * The system/conda Python runs the orchestration (download, parquet, mapping,
    dataset assembly) and imports everything here EXCEPT ``fcstd_parser``.
  * FreeCAD's bundled ``python.exe`` runs ``fcstd_parser`` because only it can
    ``import FreeCAD``. The orchestrator shells out to it as a subprocess.
"""
