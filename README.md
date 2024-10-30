# N1KDO IOT Band Selector for Elecraft K3 & K4 

This project is intended to operate a remote antenna switch.

How it it different than commercial-off-the-shelf solutions?
* Direct interface with Elecraft 15-Pin interface
* Wireless! It runs over Wifi, no wiring, no lightning arrestors
* Automatic TX Inhibit prevents TX into wrong/no antenna
* Cheap cheap
* Open Source Hardware and Software.  Do what you will with attribution.

![Band Selector](images/band-selector.jpg "Band Selector") Band Selector

![With K3](images/with-k3.jpg "Interfaced with K3") Interfaced with K3

The project is in two pieces:

  * The [Antenna Switch Controller](https://github.com/n1kdo/AntennaSwitchControl) provides a IOT endpoint for managing a 2x6 or 2x8
    antenna switch: https://github.com/n1kdo/AntennaSwitchControl
  * The Band Selector interfaces with a K3 or K4 radio, and provides the following functions:
    * Decodes selected bands from Elecraft radio AUX jack.
    * Requests antenna from the controller.
    * If the requested band antenna cannot be selected, activate the radios'  TX INHIBIT
      logic to prevent transmit.
    * The Band Selector includes a 2nd circuit board for the display.
  
This repository contains the hardware and software for The Band Selector: 
  * `kicad` folder contains the electronic design.
  * `src` folder contains the software.
  * [Bill of Materials](BOM.md "Bill of Materials")

Note that the software is licensed under BSD "2-Clause" license, except as where noted.

The hardware is licensed under terms of the "Creative Commons Attribution-ShareAlike 4.0 International Public License."