; UNDERTONE 1.0 engine (NMOS 6502 subset, runs on the 45GS02)
; a psinco. production. (C) 2026 Dawid Blachowski, MIT licence.
;
; Called from BASIC 65 with SYS $1800. Runs with interrupts off. Ends by itself when the
; accelerando reaches 25 Hz, or at once on any key or a fire button (joystick or left mouse
; button, either port).
; Each frame starts when the hardware frame counter $D7FA changes.
; Rate: a 16-bit phase accumulator. Every refresh phase += inc; f = 50 * inc / 65536 Hz.
;   State A while phase < $8000, state B above. A wrap of the phase starts a new cycle (a flash).
;   Every P_K refreshes inc grows by inc/256: one way only, from 3.125 Hz up to 25 Hz.
; Picture: the two states are always opposites. Three palettes (P_PAL):
;   0 white against black only.
;   1 in turns: 256 flashes of white against black, then one turn of the colour wheel (256 flashes)
;     from the pair closest to white and black (entry 43, yellow against blue) round to it again;
;     then white against black again, and so on.
;   2 the colour wheel alone: from entry 43, one step each flash, one turn every 256 flashes.
;   For a path point c and an amplitude a (Full 1, Soft 0.4), per channel in linear light:
;   state A = 0.5 + a*(c - 0.5), state B = 0.5 - a*(c - 0.5).
; Sound:
;   tick   a one-refresh noise tick on each state change; A right (SID 1), B left (SID 3);
;          its pitch follows the lightness of the colour it marks (P_MOD)
;   echo   each tick again P_EDLY refreshes later on the other side, through a low filter (P_ECHO)
;   tone   pulse waves at 32f and 33f on SID 2 (right) and SID 4 (left): the pitch rises with the
;          rate and the pair beats at f; the filter opens one way with the accelerando
;   P_SOUND bit 0 tick (with its echo), bit 1 tone.
; Tables live in two palette banks the text does not use (numbers in P_BT1, P_BT2):
;   bank T1: magnitudes |c-0.5|*256 (0..128) of the hue wheel, R / G / B arrays
;   bank T2: R array = tick pitch for each luminance (linear 0..255 -> noise pitch, high byte),
;            G array = gamma table (linear 0..255 -> palette register value, nybbles reversed),
;            B array = signs (bits 0..2: hue channel below 0.5)
; The screen (border and background) shows palette entry 254 of the text bank.
; Memory: code $1800-$1E7F, parameters and state $1E80-$1EFF (bank 0, kept free for programs).

* = $1800

; ---- parameters (BASIC writes them; the engine updates P_INCL/P_INCH) ----
P_INCL  = $1E80   ; phase increment per refresh, $1000 (3.125 Hz) .. $8000 (25 Hz)
P_INCH  = $1E81
P_SOFT  = $1E82   ; 1 soft, 0 full
P_SOUND = $1E83   ; layers: bit 0 tick, bit 1 tone
P_PAL   = $1E84   ; palette: 0 white against black, 1 in turns with the colour wheel, 2 the wheel
P_K     = $1E85   ; accelerando: refreshes per step of x(1 + 1/256)
P_BT1   = $1E86   ; palette bank with the hue magnitudes
P_BT2   = $1E87   ; palette bank with tick pitches, gamma table, signs
P_ECHO  = $1E88   ; 1 echo on
P_MOD   = $1E89   ; 1 tick pitch follows lightness
P_KFL   = $1E8A   ; tone factor: SID frequency of 32f = inc * KF / 65536
P_KFH   = $1E8B
P_VS    = $1E8C   ; tick volume (0..15)
P_VT    = $1E8D   ; tone volume at Full (0..15)
P_EDLY  = $1E8E   ; echo delay in refreshes (1..7)
; ---- results (engine writes, BASIC reads) ----
P_EXIT  = $1E8F   ; 0: reached 25 Hz; else the key (ASCII) that stopped it; $FF: a fire button
D_FR0   = $1E90   ; frames run, 24 bit
D_FR1   = $1E91
D_FR2   = $1E92
D_MISS  = $1E93   ; frames missed (saturates at 255)
; ---- state ----
V_SEG   = $1E94   ; 0 white against black, 1 colour wheel
V_CNT   = $1E95   ; flashes in this segment, 0..255
V_PHL   = $1E96   ; phase
V_PHH   = $1E97
V_ST    = $1E98   ; state on screen: 0 = A, 1 = B
V_NST   = $1E99   ; state for the next frame
V_SK    = $1E9A   ; ticks for the next frame: bit 0 right (A), bit 1 left (B)
V_LFC   = $1E9B   ; last frame counter value
V_S20   = $1E9C   ; saved border colour
V_S21   = $1E9D   ; saved background colour
V_S70   = $1E9E   ; saved palette bank selection
V_B70   = $1E9F   ; $D070 without MAPEDPAL bits
V_W70   = $1EA0   ; $D070 mapping the text bank
V_KC    = $1EA1   ; accelerando refresh counter
V_HH    = $1EA2   ; hue wheel index
V_AMPL  = $1EA3   ; amplitude, 0..256
V_AMPH  = $1EA4
V_AR    = $1EA5   ; state A colour, palette register format
V_AG    = $1EA6
V_AB    = $1EA7
V_BR    = $1EA8   ; state B colour
V_BG    = $1EA9
V_BB    = $1EAA
V_TMP   = $1EAB
V_SGN   = $1EAC   ; sign bits for the three channels
V_MR    = $1EAD   ; magnitudes for the three channels
V_MG    = $1EAE
V_MB    = $1EAF
V_FAC1  = $1EB0   ; multiply
V_FAC2  = $1EB1
V_LA    = $1EB2   ; one channel: linear, then encoded, for A and B
V_LB    = $1EB3
V_VT    = $1EB4   ; tone volume now
V_FC    = $1EB5   ; tone filter cutoff (high byte): starts at 64, only rises
V_FNL   = $1EB6   ; SID frequency of 32f
V_FNH   = $1EB7
V_GNL   = $1EB8   ; SID frequency of 33f
V_GNH   = $1EB9
V_EP    = $1EBA   ; echo ring position
V_EH    = $1EBB   ; echo ring, 8 bytes, $1EBB-$1EC2
V_M0    = $1EC3   ; 16 x 16 bit product
V_M1    = $1EC4
V_M2    = $1EC5
V_M3    = $1EC6
V_W     = $1EC7   ; luminance weight of the channel in hand
V_YAL   = $1EC8   ; luminance of state A, 255 * 255 scale
V_YAH   = $1EC9
V_YBL   = $1ECA   ; luminance of state B
V_YBH   = $1ECB
V_PA    = $1ECC   ; tick pitch of A
V_PB    = $1ECD   ; tick pitch of B
V_STP   = $1ECE   ; accelerando steps
V_T3    = $1ECF
V_T4    = $1ED0
V_JOK   = $1ED1   ; 1: the joystick ports can be read (no colour RAM at $DC00)
V_SDC0  = $1ED2   ; saved CIA 1 port A
V_FPRV  = $1ED3   ; fire buttons last frame: $10 down, 0 up

start:
        SEI
        CLD
        LDA #$47          ; VIC-IV I/O personality
        STA $D02F
        LDA #$53
        STA $D02F
        LDA $D020
        STA V_S20
        LDA $D021
        STA V_S21
        LDA $D070
        STA V_S70
        AND #$3F
        STA V_B70
        LDA V_S70         ; MAPEDPAL := BTPALSEL (bits 5-4 -> 7-6)
        AND #$30
        ASL A
        ASL A
        ORA V_B70
        STA V_W70
        STA $D070
flush:
        LDA $D610         ; empty the hardware key queue
        BEQ flushed
        STA $D610
        JMP flush
flushed:
        LDA $D030         ; joysticks: only while the CIA is visible at $DC00
        AND #$01
        EOR #$01
        STA V_JOK
        BEQ nojoy
        LDA $DC00
        STA V_SDC0
        LDA #$FF          ; no keyboard row selected: port A and B show the joysticks only
        STA $DC00
        JSR rdfire
        STA V_FPRV        ; a button held at the start must be let go first
nojoy:
        LDA #$00
        STA D_FR0
        STA D_FR1
        STA D_FR2
        STA D_MISS
        STA V_PHL
        STA V_PHH
        STA V_KC
        STA V_SEG
        STA V_CNT
        STA V_HH
        STA P_EXIT
        STA V_EP
        STA V_STP
        LDX #$07
clrring:
        STA V_EH,X
        DEX
        BPL clrring
        LDA P_PAL         ; the colour wheel alone starts at entry 43, yellow against blue
        CMP #$02
        BNE stbw
        LDA #$01
        STA V_SEG
        LDA #$2B
        STA V_HH
stbw:
        LDA #$40          ; the tone filter starts low and only opens
        STA V_FC
        LDA #$01
        STA V_ST
        JSR sidinit
        JSR setamp
        JSR colours
        JSR nextst
        JSR show          ; first colour (white) before pointing the screen at it
        LDA #$FE
        STA $D020
        STA $D021
        LDA $D7FA
        STA V_LFC

main:
        LDA $D7FA
        CMP V_LFC
        BEQ main
        TAX               ; ---- new frame ----
        JSR show
        TXA
        PHA
        JSR sidframe      ; uses X
        PLA
        TAX
        SEC               ; missed frames = delta - 1
        SBC V_LFC
        STX V_LFC
        CMP #$01
        BEQ nomiss
        SEC
        SBC #$01
        CLC
        ADC D_MISS
        BCC misssat
        LDA #$FF
misssat:
        STA D_MISS
nomiss:
        INC D_FR0
        BNE frdone
        INC D_FR1
        BNE frdone
        INC D_FR2
frdone:
        LDA V_NST
        STA V_ST
        JSR keys
        BCS exit
        JSR accel
        BCS exit          ; 25 Hz reached: the piece ends
        CLC               ; phase += inc; a wrap starts a new cycle
        LDA V_PHL
        ADC P_INCL
        STA V_PHL
        LDA V_PHH
        ADC P_INCH
        STA V_PHH
        BCC noflash
        JSR flash
noflash:
        JSR nextst
        JMP main

exit:
        JSR sidoff
        LDA V_JOK
        BEQ exnojoy
        LDA V_SDC0
        STA $DC00
exnojoy:
        LDA V_S70
        STA $D070
        LDA V_S20
        STA $D020
        LDA V_S21
        STA $D021
        CLI
        RTS

; ---- put the colour of the next state into entry 254 (text bank mapped) ----
show:
        LDA V_NST
        BNE showb
        LDA V_AR
        STA $D1FE
        LDA V_AG
        STA $D2FE
        LDA V_AB
        STA $D3FE
        RTS
showb:
        LDA V_BR
        STA $D1FE
        LDA V_BG
        STA $D2FE
        LDA V_BB
        STA $D3FE
        RTS

; ---- state of the next frame from the phase; ticks on a change ----
nextst:
        LDA V_PHH
        AND #$80
        BEQ nsA
        LDA #$01
nsA:
        STA V_NST
        LDA #$00
        STA V_SK
        LDA V_NST
        CMP V_ST
        BEQ nsdone
        LDA V_NST
        BNE nsB
        LDA #$01
        STA V_SK
        RTS
nsB:
        LDA #$02
        STA V_SK
nsdone:
        RTS

; ---- a new cycle. In turns: 256 flashes of white against black, then one turn of the wheel ----
flash:
        INC V_CNT
        BNE flstay
        LDA P_PAL         ; 256 flashes done: in turns, the other world
        CMP #$01
        BNE flstay        ; one palette only: white against black stays, the wheel turns on
        LDA V_SEG
        EOR #$01
        STA V_SEG
        BEQ flnew         ; back to white against black
        LDA #$2B          ; the wheel starts at entry 43, yellow against blue
        STA V_HH
flnew:
        JMP colours
flstay:
        LDA V_SEG
        BEQ flret         ; white against black stands still
        INC V_HH          ; the wheel turns one way
        JMP colours
flret:
        RTS

; ---- amplitude: Soft 102, Full 256 ----
setamp:
        LDA P_SOFT
        BNE sasoft
        LDA #$00
        STA V_AMPL
        LDA #$01
        STA V_AMPH
        RTS
sasoft:
        LDA #$66
        STA V_AMPL
        LDA #$00
        STA V_AMPH
        RTS

; ---- 8 x 8 bit multiply: V_FAC1 * V_FAC2 -> A (high byte), V_FAC1 (low byte); uses X ----
mul8:
        LDA #$00
        LDX #$08
        LSR V_FAC1
mulp:
        BCC mulns
        CLC
        ADC V_FAC2
mulns:
        ROR A
        ROR V_FAC1
        DEX
        BNE mulp
        RTS

; ---- both states' colours, their lightness and tick pitches, the tone volume ----
colours:
        LDY P_BT2
        JSR mapbank
        LDA V_SEG
        BNE cohue
        LDA #$80          ; white against black: magnitude 128 on every channel, A the light one
        STA V_MR
        STA V_MG
        STA V_MB
        LDA #$00
        STA V_SGN
        JMP cocalc
cohue:
        LDX V_HH
        LDA $D300,X       ; bits 0-2: hue channels below 0.5
        AND #$07
        STA V_SGN
        LDY P_BT1
        JSR mapbank
        LDA $D100,X
        STA V_MR
        LDA $D200,X
        STA V_MG
        LDA $D300,X
        STA V_MB
        LDY P_BT2         ; gamma and pitch tables are in bank T2
        JSR mapbank
cocalc:
        LDA #$00
        STA V_YAL
        STA V_YAH
        STA V_YBL
        STA V_YBH
        LDA #$36          ; red: luminance weight 54/255
        STA V_W
        LDA V_MR
        LDY #$01
        JSR chan
        LDA V_LA
        STA V_AR
        LDA V_LB
        STA V_BR
        LDA #$B7          ; green: 183/255
        STA V_W
        LDA V_MG
        LDY #$02
        JSR chan
        LDA V_LA
        STA V_AG
        LDA V_LB
        STA V_BG
        LDA #$12          ; blue: 18/255
        STA V_W
        LDA V_MB
        LDY #$04
        JSR chan
        LDA V_LA
        STA V_AB
        LDA V_LB
        STA V_BB
        LDX V_YAH         ; tick pitch of each state from its luminance
        LDA $D100,X
        STA V_PA
        LDX V_YBH
        LDA $D100,X
        STA V_PB
        LDA V_W70
        STA $D070
        LDA V_AMPH        ; tone volume: VT at Full, VT * 102 / 256 at Soft
        BEQ cotsoft
        LDA P_VT
        STA V_VT
        RTS
cotsoft:
        LDA V_AMPL
        STA V_FAC1
        LDA P_VT
        STA V_FAC2
        JSR mul8
        STA V_T3
        LDA V_FAC1
        CLC
        ADC #$80
        LDA V_T3
        ADC #$00
        STA V_VT
        RTS

; ---- one channel: A = magnitude, Y = sign bit, V_W = weight.
;      Returns encoded A in V_LA, B in V_LB; adds weight * linear value to each luminance ----
chan:
        STA V_FAC2
        TYA
        AND V_SGN
        STA V_TMP         ; non-zero: this channel is below 0.5
        LDA V_AMPH
        BEQ chmul
        LDA V_FAC2        ; amplitude 256: offset = magnitude
        JMP chp
chmul:
        LDA V_AMPL
        STA V_FAC1
        JSR mul8          ; offset = amplitude * magnitude / 256
chp:
        STA V_FAC1
        CLC
        LDA #$80
        ADC V_FAC1
        BCC chnc
        LDA #$FF          ; 256 -> 255
chnc:
        STA V_LA          ; 128 + offset
        SEC
        LDA #$80
        SBC V_FAC1
        STA V_LB          ; 128 - offset
        LDA V_TMP
        BEQ chpos
        LDA V_LA          ; below 0.5: state A takes the lower value
        LDX V_LB
        STA V_LB
        STX V_LA
chpos:
        LDA V_LA          ; luminance of A += weight * linear value
        STA V_FAC1
        LDA V_W
        STA V_FAC2
        JSR mul8
        STA V_T3
        CLC
        LDA V_YAL
        ADC V_FAC1
        STA V_YAL
        LDA V_YAH
        ADC V_T3
        STA V_YAH
        LDA V_LB          ; and of B
        STA V_FAC1
        LDA V_W
        STA V_FAC2
        JSR mul8
        STA V_T3
        CLC
        LDA V_YBL
        ADC V_FAC1
        STA V_YBL
        LDA V_YBH
        ADC V_T3
        STA V_YBH
        LDX V_LA          ; encode through the gamma table
        LDA $D200,X
        STA V_LA
        LDX V_LB
        LDA $D200,X
        STA V_LB
        RTS

; ---- map palette bank Y at $D100-$D3FF ----
mapbank:
        LDA bankbits,Y
        ORA V_B70
        STA $D070
        RTS
bankbits:
        .byte $00,$40,$80,$C0

; ---- accelerando, always on: every P_K refreshes inc grows by inc/256.
;      Carry set when 25 Hz is reached: the piece ends there. ----
accel:
        INC V_KC
        LDA V_KC
        CMP P_K
        BCC acno
        LDA #$00
        STA V_KC
        INC V_STP
        LDA V_STP
        AND #$03
        BNE acstep
        INC V_FC          ; the tone filter opens one step every 4 steps and never closes
acstep:
        CLC
        LDA P_INCL
        ADC P_INCH
        STA P_INCL
        LDA P_INCH
        ADC #$00
        STA P_INCH
        CMP #$80
        BCC acno
        LDA #$00
        STA P_INCL
        LDA #$80
        STA P_INCH
        SEC
        RTS
acno:
        CLC
        RTS

; ---- stop on any key, or when a fire button goes down (carry set) ----
keys:
        LDA $D610
        BEQ kfire
        STA $D610         ; take it off the queue
        STA P_EXIT
        SEC
        RTS
kfire:
        LDA V_JOK
        BEQ kno
        JSR rdfire
        CMP V_FPRV
        BEQ kno           ; no change
        STA V_FPRV
        TAX
        BEQ kno           ; a button let go
        LDA #$FF
        STA P_EXIT
        SEC
        RTS
kno:
        CLC
        RTS

; ---- fire buttons of both ports (bit 4 of CIA 1 port A and B, low when down): A = $10 if down ----
rdfire:
        LDA $DC00
        AND $DC01
        AND #$10
        EOR #$10
        RTS

; ---- 16 x 16 bit multiply: V_M3..V_M0 = inc * KF ----
mul16:
        LDA P_INCL        ; the low half starts as the multiplier
        STA V_M0
        LDA P_INCH
        STA V_M1
        LDA #$00
        STA V_M2
        STA V_M3
        LDX #$10
m16l:
        LDA V_M0
        AND #$01
        BEQ m16s
        CLC               ; add the multiplicand to the high half
        LDA V_M2
        ADC P_KFL
        STA V_M2
        LDA V_M3
        ADC P_KFH
        STA V_M3
        JMP m16r
m16s:
        CLC
m16r:
        ROR V_M3          ; shift all 33 bits right
        ROR V_M2
        ROR V_M1
        ROR V_M0
        DEX
        BNE m16l
        RTS

; ---- SID frequencies of the tone pair: 32f and 33f = 32f + 32f/32 ----
tonefreq:
        JSR mul16
        LDA V_M2
        STA V_FNL
        STA V_GNL
        LDA V_M3
        STA V_FNH
        STA V_GNH
        LDX #$05
tf5:
        LSR V_GNH
        ROR V_GNL
        DEX
        BNE tf5
        CLC
        LDA V_GNL
        ADC V_FNL
        STA V_GNL
        LDA V_GNH
        ADC V_FNH
        STA V_GNH
        RTS

; ---- sound. SID 1 (right): voice 1 tick of A, voice 2 echo of B.
;      SID 3 (left): voice 1 tick of B, voice 2 echo of A. Echo voices pass a low filter.
;      SID 2 (right) and SID 4 (left): voice 1 tone 32f, voice 2 tone 33f, both filtered. ----
sidinit:
        LDX #$00          ; clear registers 0-24 of all four SIDs
sic:
        TXA
        AND #$1F
        CMP #$19
        BCS sicn
        LDA #$00
        STA $D400,X
sicn:
        INX
        CPX #$80
        BNE sic
        LDA #$40          ; noise pitch for ticks and echoes
        STA $D401
        STA $D408
        STA $D441
        STA $D448
        LDA #$80          ; noise, gate off
        STA $D404
        STA $D40B
        STA $D444
        STA $D44B
        LDA #$20          ; echo filter: low pass at a low cutoff, voice 2 only
        STA $D416
        STA $D456
        LDA #$02
        STA $D417
        STA $D457
        LDA #$08          ; tone voices: pulse width 50%, sustain 15
        STA $D423
        STA $D42A
        STA $D463
        STA $D46A
        LDA #$F0
        STA $D426
        STA $D42D
        STA $D466
        STA $D46D
        LDA #$40          ; pulse, gate off
        STA $D424
        STA $D42B
        STA $D464
        STA $D46B
        LDA #$63          ; tone filter: resonance 6, voices 1 and 2
        STA $D437
        STA $D477
        LDA #$10          ; low pass, volume 0 until the first frame
        STA $D418
        STA $D438
        STA $D458
        STA $D478
        RTS

sidframe:
        LDA P_SOUND       ; ---- tick ----
        AND #$01
        STA V_T3          ; tick layer on?
        BEQ sfs0
        LDA V_SK
sfs0:
        STA V_T4          ; ticks this frame
        LDA P_MOD         ; tick pitch: the lightness of the colour it marks, or fixed
        BEQ sfpfix
        LDA V_PA
        STA $D401
        LDA V_PB
        STA $D441
        JMP sfgate
sfpfix:
        LDA #$40
        STA $D401
        STA $D441
sfgate:
        LDA V_T4
        AND #$01
        JSR gatebit
        STA $D404
        LDA V_T4
        AND #$02
        JSR gatebit
        STA $D444
        LDX V_EP          ; ---- echo: the ring keeps the ticks of the last 8 frames ----
        LDA V_T4
        STA V_EH,X
        TXA
        SEC
        SBC P_EDLY
        AND #$07
        TAY
        LDA V_EH,Y
        LDY P_ECHO
        BNE sfe1
        LDA #$00
sfe1:
        STA V_T4          ; ticks P_EDLY frames ago
        INX
        TXA
        AND #$07
        STA V_EP
        LDA V_T4
        AND #$01          ; the echo of A sounds left
        JSR gatebit
        STA $D44B
        LDA V_T4
        AND #$02          ; the echo of B sounds right
        JSR gatebit
        STA $D40B
        LDA V_T3          ; ---- tick volume ----
        BEQ sfv0
        LDA P_VS
sfv0:
        ORA #$10
        STA $D418
        STA $D458
        LDA P_SOUND       ; ---- tone ----
        AND #$02
        BNE sft1
        LDA #$40
        STA $D424
        STA $D42B
        STA $D464
        STA $D46B
        LDA #$10
        STA $D438
        STA $D478
        RTS
sft1:
        JSR tonefreq
        LDA V_FNL
        STA $D420
        STA $D460
        LDA V_FNH
        STA $D421
        STA $D461
        LDA V_GNL
        STA $D427
        STA $D467
        LDA V_GNH
        STA $D428
        STA $D468
        LDA #$41          ; pulse, gate on
        STA $D424
        STA $D42B
        STA $D464
        STA $D46B
        LDA V_FC
        STA $D436
        STA $D476
        LDA V_VT
        ORA #$10
        STA $D438
        STA $D478
        RTS
gatebit:                  ; Z clear: A = $81 (noise, gate on), else $80
        BEQ gb0
        LDA #$81
        RTS
gb0:
        LDA #$80
        RTS

sidoff:
        LDA #$80
        STA $D404
        STA $D40B
        STA $D444
        STA $D44B
        LDA #$40
        STA $D424
        STA $D42B
        STA $D464
        STA $D46B
        LDA #$00
        STA $D417
        STA $D437
        STA $D457
        STA $D477
        STA $D418
        STA $D438
        STA $D458
        STA $D478
        RTS
