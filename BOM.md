# Bill of Materials for Band Selector

This is the Bill of Materials for the N1KDO Band Selector.

All the parts -- except the circuit boards -- were ordered from Mouser.com.

The circuit boards came from Oshpark.com.

Costs are approximate, they were checked 2025-01-05.  

## Display Board Bill of Materials

| id           | desc                                                 | mfg               | part                      | price |       ext |
|--------------|------------------------------------------------------|-------------------|---------------------------|------:|----------:|
| C1           | 1 uF 35 V tantalum                                   | Vishay            | 199D105X9035A2B1E3        |  1.76 |      1.76 |
| J1           | 1x16 right angle sip connector                       | Molex             | 22-28-8160                |  1.40 |      1.40 |
| R1           | Carbon Film Resistors - Through Hole 1/4W 220 Ohm 5% | Yageo             | CFR-25JB-52-220R          |  0.10 |      0.10 |
| RV1          | 10K ohm trim pot                                     | Amphenol Piher    | N6-L50T0C-103             |  0.72 |      0.72 |
| SW1, 2, 3, 4 | Tactile Pushbutton                                   | Same Sky          | TS02-66-130-BK-100-LCR-D  |  0.14 |      0.56 |
| U1           | 2x20 backit LCD display 3.3 volt                     | New Haven Display | NHD-0220FZ-FSW-GBW-P-33V3 | 12.66 |     12.66 |
| PCB          | N1KDO Display Board PCB V 0.0.4                      |                   | Oshpark                   |  7.30 |      7.30 |
| **Total**    |                                                      |                   |                           |       | **31.50** |

## Main Board Bill of Materials

| id                | desc                                                                    | mfg                   | part             | price |   ext |
|-------------------|-------------------------------------------------------------------------|-----------------------|------------------|------:|------:|
| C1,C2,C3,C4,C5,C7 | 50V 0.1uF X7R 10% LS =2.54mm                                            | KEMET                 | C320C104K5R5TA   |  0.17 |  1.02 |
| C6                | (DNP) 50V 0.1uF X7R 10% LS =2.54mm                                      | KEMET                 | C320C104K5R5TA   |  0.17 |  0.00 |
| C8                | Aluminum Electrolytic Capacitors - Radial Leaded 220uF 25V              | Panasonic             | ECA-1EM221       |  0.28 |  0.28 |
| C9,C10            | Aluminum Electrolytic Capacitors - Radial Leaded 2.2uF 50volts AEC-Q200 | Panasonic             | EEU-FC1H2R2H     |  0.24 |  0.48 |
| D1,D2,D3,D4,D7    | Schottky Diodes & Rectifiers 200mA 30 Volt                              | STMicroelectronics    | BAT43            |  0.17 |  0.85 |
| D5                | Schottky Diodes & Rectifiers Vr/40V Io/1A                               | STMicroelectronics    | 1N5819           |  0.21 |  0.42 |
| D6                | (DNP) Schottky Diodes & Rectifiers 200mA 30 Volt                        | STMicroelectronics    | BAT43            |  0.17 |  0.00 |
| D8                | Rectifiers Diode, DO-41, 100V, 1A                                       | Diotec                | 1N4002           |  0.06 |  0.06 |
| D9                | Standard LEDs - Through Hole Green Diffused                             | Lite-On               | LTL-4231N        |  0.13 |  0.13 |
| D10               | Standard LEDs - Through Hole Red Diffused                               | Lite-On               | LTL-4221N        |  0.19 |  0.16 |
| F1                | Resettable Fuses - PPTC .9A 30V 100A Imax                               | LittelFuse            | RUEF090          |  0.61 |  0.61 |
| J1                | D-Sub High Density Connectors 15P MALE R/A PIN UNC 4-40 CLINCH NUTS     | Amphenol FCI          | 10090926-P154XLF |  1.65 |  1.65 |
| J2                | DC Power Connectors RT ANGL PWK JK PIN D                                | Switchcraft           | RAPC722X         |  2.21 |  2.21 |
| J3                | Board to Board & Mezzanine Connectors 16P VRT SR RECEPT MATTE TIN       | Amphenol FCI          | 75915-416LF      |  2.41 |  2.41 |
| L1,L2,L3,L4,L5,L6 | RF Inductors - Leaded RF CHOKE 100uH 5% CONFORMAL COATED                | Bourns                | 78F101J-TR-RC    |  0.18 |  1.08 |
| L7                | (DNP) RF Inductors - Leaded RF CHOKE 100uH 5% CONFORMAL COATED          | Bourns                | 78F101J-TR-RC    |  0.18 |  0.00 |
| Q1,Q2             | MOSFETs Small Signal MOSFET 60V 200mA 5 Ohm Single N-Channel TO-92      | onsemi / Fairchild    | 2N7000           |  0.38 |  0.76 |
| R1,R8             | Carbon Film Resistors - Through Hole 1/4W 100 Ohm 5%                    | Yageo                 | CFR-25JB-52-100R |  0.04 |  0.08 |
| R2,R3,R4,R5,R6,R9 | Carbon Film Resistors - Through Hole 1/4W 10K Ohm 5%                    | Yageo                 | CFR-25JB-52-10K  |  0.02 |  0.10 |
| R10               | Carbon Film Resistors - Through Hole 1/4W 330 Ohm 5%                    | Yageo                 | CFR-25JB-52-330R |  0.02 |  0.02 |
| R11               | Carbon Film Resistors - Through Hole 1/4W 470 Ohm 5%                    | Yageo                 | CFR-25JB-52-470R |  0.02 |  0.02 |
| U1                | Single Board Computers Raspberry Pi Pico W                              | Raspberry Pi          | SC0918           |  6.00 |  6.00 |
| U2                | Linear Voltage Regulators 5.0V 1.5A Positive                            | STMicroelectronics    | L7805CV          |  0.48 |  0.48 |
| PCB               | N1KDO Band Selector Board PCB V 0.0.4                                   | Oshpark               |                  |     ? | 21.20 |
| Enclosure         | Enclosures, Boxes, & Cases FR ABS w/Flanged Lid 7.6x4.4x2.2" Black      | Hammond Manufacturing | 1591XXEFLBK      | 12.89 | 12.89 |
| **Total**         |                                                                         |                       |                  |       | 50.50 |

Total Band Selector approximate cost $82/radio.

n1kdo 20250105
