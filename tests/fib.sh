function fib() {
  if [ $1 -lt 2 ]
  then
    echo $1
  else
    a=$(fib $(($1-1)))
    b=$(fib $(($1-2)))
    echo $(($a+$b))
  fi
}

fib 5
