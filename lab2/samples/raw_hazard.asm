.text
main:
ADDIU $r1,$r0,A
LW $r2,0($r1)
ADD $r3,$r2,$r2
ADD $r4,$r3,$r2
SW $r4,4($r1)

.data
A: .word 5, 0, 0, 0
