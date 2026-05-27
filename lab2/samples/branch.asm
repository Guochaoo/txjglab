.text
main:
ADDIU $r1,$r0,0
BEQZ $r1,target
ADDIU $r2,$r0,99
ADDIU $r3,$r0,88
target:
ADDIU $r4,$r0,7
SW $r4,0($r0)

.data
A: .word 0, 0, 0, 0
