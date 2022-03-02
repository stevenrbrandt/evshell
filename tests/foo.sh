ls
echo $(date +%m/%d/%Y )
for a in 1 2 3
do
    echo $a
    for b in 4 5 6
    do
        echo $a$b
    done
done
