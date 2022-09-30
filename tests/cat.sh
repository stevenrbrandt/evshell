echo foo > x.tmp
echo bar >> x.tmp
cat < x.tmp
rm -f x.tmp
echo word1 >&2
echo word2 1>&2
ls xxzxx 2>err.out
perl -p -i -e 's{/usr/bin/}{}' err.out
cat err.out
