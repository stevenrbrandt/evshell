#(echo a && (echo b))
echo a && (echo b > b.txt && (echo d > d.txt)) && echo c
cat b.txt
cat d.txt
