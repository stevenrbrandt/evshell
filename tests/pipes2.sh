echo xxx1 | sed s/xxx/yyy/
echo xxx2 | sed s/xxx/yyy/
for i in $(seq 1 10)
do
  echo foo $i | sed s/foo/bar/
done
