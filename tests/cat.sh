echo foo > x
echo bar >> x
cat < x
echo word1 >&2
echo word2 1>&2
ls xxzxx 2>err.out
perl -p -i -e 's{/usr/bin/}{}' err.out
cat err.out
