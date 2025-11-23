# Implement Message Queue.  (DONE)
  messages drive actions

  ## Message types

  * buttons 1-4 falling edge: control UI functions.
  * pwrsense change.  can choose to turn on radio.
  * band change.  send to band logic
  * http responses -- valid
    * band request responses
    * information request responses
  * http responses -- failures
    * timeout or unreachable
  * update display, write, home, clear, moveto, cursor on/off, value up/down?
  * timer event

implement task that reads hardware inputs:

* buttons 1-4 -- either edge
* PWRSENSE -- either edge
* band data b0-b3 collectively as 4-bit value 0-F -- send event on edge
* 
send message into message queue

implement task that runs async http transaction, enqueues result

implement task (?) to update display?  
do I need this?  all fast except clear and home, they need 5 ms.

Make the message a tuple.  in many cases, the message will be a 1-tuple, if 
there is such a thing.  In other cases, additional data may be references by
2nd (and subsequent) tuple values.

## messages by ID:

1, 2, 3, 4: button ID, 2nd part of tuple is short (0) or long (1) press
10: pwrsense, 2nd value is hi/lo
20-2x: network status messages, (code, text) -- is this used?
50: network down/up message, (50, 0|1)  **NOT USED**

90, 91, write LCD line 0,1 (9x,text)
100: band change, 2nd value is new band #
201 api status response, text in 2nd value of tuple
202 api select antenna, text in 2nd value of tuple
1000+: timer events.  

# Display update process.

Concept: the display should show the radio/band/current antenna as the default.

The current access point and IP should also be available. if the network is not connected,
or there is no connection to the antenna switch, that message should have highest priority.

Network status change messages (connecting, failed, connected) should pop up for N seconds.

menu buttons:
```
                  +------------------------------+
                  |   +----------------------+   |
    radio status  | o | 123456 Line 1 567890 | o |  ^ antenna up
  network status  | o | 123456 Line 2 567890 | o |  v antenna down
                  |   +----------------------+   |
 red LED inhibit  |  *                        *  |  green LED power
                  +------------------------------+

```

some? message updates set a timer to make that 2-line 'page' of pop that
message to the top for N seconds,  
button activity resets timeout,   
but menu change may update display and set timeout
a timeout reset causes last message (stack or 2-deep?) to be shown.

## Display Messages:

### Network

Display WiFi net name and IP address.

```
12345678901234567890
  Free Public Wifi  
    192.168.0.201       
```

### Radio

Display radio name and Band and Antenna Name

```
12345678901234567890
  Elecraft K3 40M  
  40 Meter Dipole         
```

* add + plus sign after antenna name if there is another antenna available... DONE
  * up/down buttons select antenna only when this page is displayed

### Activity

* other messages:  
  * Network
     * "Connecting to WLAN..."  
     * "setting hostname / ant-switch"  
     * "connecting to / fbi surveillance van"
  * Radio
    * "Unknown Rig No Power"  
    * / Unknown Antenna  
    * / "No Antenna Switch!" -- cannot reach antenna switch

### Menu:

* can menu go away?  YES DONE  
* right now there is an option for station or access point. REMOVED.  
  * disable config change of ap_mode. DONE
  * when not in ap_mode, disable config ssid & password write  
    * exactly how much to disable? hostname? dhcp? dns?  
* use held button at powerup to set ap_mode -- must have access to hardware.
  * hold down switch 1 at power up to select AP/setup mode. DONE.

### Config

* make config into Config class and encapsulate functions? LATER
