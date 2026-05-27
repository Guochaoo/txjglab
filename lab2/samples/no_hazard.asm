.text
main:
ADDIU $r1,$r0,A
ADDIU $r4,$r0,B
ADDIU $r5,$r0,1
LW $r2,0($r1)
LW $r3,4($r1)
ADD $r6,$r5,$r5
SW $r2,0($r4)
SW $r3,4($r4)

.data
A: .word 1, 2, 4, 8
B: .word 1, 2, 3, 4
