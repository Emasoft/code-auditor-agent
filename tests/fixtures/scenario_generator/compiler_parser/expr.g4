// fixture for compiler_parser — minimal ANTLR4 grammar for arithmetic expressions.
//
// The compiler_parser fingerprint requires either a *.g4 / *.y / *.lex /
// *.pest / *.tree-sitter primary file PLUS a disambiguator function
// like `def parse_*` in a Python source. This grammar covers the
// primary-file half.

grammar Expr;

prog
    : stat+ EOF
    ;

stat
    : expr NEWLINE
    | NEWLINE
    ;

expr
    : expr ('*'|'/') expr
    | expr ('+'|'-') expr
    | INT
    | '(' expr ')'
    ;

INT     : [0-9]+ ;
NEWLINE : '\r'? '\n' ;
WS      : [ \t]+ -> skip ;
