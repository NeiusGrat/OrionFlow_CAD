class CompilerError(Exception):
    pass


class SketchCompilationError(CompilerError):
    pass


class FeatureCompilationError(CompilerError):
    pass
