x=foo.c
echo ${x%.c}
echo ${x%%.c}
E=.c
echo ${x%$E}
echo ${x%%$E}
