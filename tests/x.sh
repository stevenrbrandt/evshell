echo "0($0) 1($1) 2($2)"
if [ "x$1" = "x" ]
then
    echo "HERE"
    bash $0 a b c
else
    echo done $1
fi
