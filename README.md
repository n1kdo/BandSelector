# N1KDO IOT Band Selector for Elecraft K3 & K4 

This project is intended to operate a remote antenna switch.

The project is in two pieces:

  * The Antenna Switch Controller provides a IOT endpoint for managing a 2x6 or 2x8
    antenna switch:
    * software: https://github.com/n1kdo/AntennaSwitchControl
    * hardware: https://github.com/n1kdo/16-relays
  * The Band Selector interfaces with a K3 or K4 radio, and provides the following functions:
    * Decodes selected bands from Elecraft radio AUX jack.
    * Requests antenna from the controller.
    * If the requested band antenna cannot be selected, activate the radios'  TX INHIBIT
      logic to prevent transmit.  
  
This repository contains the hardware and software for The Band Selector: 
  * `kicad` folder contains the electronic design.
  * `src` folder contains the software.

Note that the software is licensed under BSD "2-Clause" license, except as where noted.

The hardware is licensed under terms of the "Creative Commons Attribution-ShareAlike 4.0 International Public License."