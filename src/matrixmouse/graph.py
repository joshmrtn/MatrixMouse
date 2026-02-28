"""
matrixmouse/graph.py

Builds and maintains a call graph of the project for analysis.

Provides data for code inspection tools.

Responsibile for tracking:
    - Function and method definitions (name, file, line number, docstring, args)
    - Class definitions (name, file, methods, docstring).
    - Call relationships (what each function calls; what calls each function).
    - Import relationships per file.

Limitations: static analysis only. Dynamic dispatch, `getattr`, and heavily decorated code may be incomplete.
"""
