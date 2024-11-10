# UI Design Nodes for N1KDO Band Selector

## Front Panel Layout 

(O) is a button.

```
+------------------------------------------------+
|                                                |
| Menu  O   +----------------------+      O ↑    |
|           | 2 x 20 alphanumeric  |             |
|           | 12345678901234567890 |             |
| Edit  O   +----------------------+      O ↓    |
|                                                |
+------------------------------------------------+
```

## Switch to Button Assignments

| Switch | Function |
|--------|----------|
| SW1    | Menu     |
| SW2    | Edit     |
| SW3    | Up       |
| SW4    | Down     |

## Navigation and Editing

The _Menu_ button enters "Menu" mode.

When in menu mode, the up/down buttons select the next or prior display option.

If a value is editable, the _name_ of the value is shown on the top line, and the
_value_ of the item is shown on the bottom line.

To edit a value, press the "edit" button.  Now the up/down buttons will scroll 
through the lit of available options for that value.  Press "edit" to accept the
currently shown value, or press "menu" to revert to the saved value.

When *not* in "menu mode", the 2x2o display shows the radio status:

* the top line displays the radio name and selected band.
* the bottom line displays the selected antenna.

When *not* in menu mode, the up/down buttons can be used to select other 
antennas that are compatible with the current band.

When *not* in menu mode, the "edit" button will cause the network configuration
to be shown on the display.

## Menu State Machine(s)

| State Number | Function                       | Const                |
|:------------:|:-------------------------------|----------------------|
|      0       | Display Radio Status           | RADIO_STATUS_STATE   |
|      1       | Display Network Status         | NETWORK_STATUS_STATE |
|     20x      | Menu Mode, display menu item X | MENU_MODE_STATE_BASE |
|     30x      | Menu Mode, edit menu item X    | MENU_EDIT_STATE_BASE |
|              | TBD?                           |                      |

### State 0  -- Display Radio Status

In this state the display shows two lines:

* Radio Name and Band
* Selected Antenna

Actions from this state:

| Button | Action                                                  |
|:-------|:--------------------------------------------------------|
| Menu   | Switch to state 20x                                     | 
| Edit   | Update Display to Network Status <br>Switch to state 1. |
| Up     | switch to next compatible antenna                       |
| Down   | switch to prior compatible antenna                      | 


## State 1 -- Display Network Status

In this state the display shows two lines:

* Network SSID
* IP address of device

All actions from this state return to the radio status state (0).

| Button | Action                                               | Function               |
|:-------|:-----------------------------------------------------|:-----------------------|
| Menu   | Update display to radio status<br>Switch to state 0. | Return to Radio Status | 
| Edit   | Update display to radio status<br>Switch to state 0. | Return to Radio Status | 
| Up     | Update display to radio status<br>Switch to state 0. | Return to Radio Status | 
| Down   | Update display to radio status<br>Switch to state 0. | Return to Radio Status | 

### State 20x  -- Menu Mode, Display Item X

In this state the display shows two lines:

* Menu Item _Name_
* Menu Item _Value_

Actions from this state:

| Button | Action                                               | Function               |
|:-------|:-----------------------------------------------------|:-----------------------|
| Menu   | Update display to radio status<br>Switch to state 0. | Return to Radio Status | 
| Edit   | Switch to state 30x.                                 | Enter Edit Value Mode  |
| Up     | switch to next menu item                             | Next Item              |
| Down   | switch to prior menu item                            | Previous Item          |

### State 30x -- Edit Mode, Edit Item X

In this state, the display shows two lines:

* Menu Item _Name_
* Menu Item _Value_

If the cursor can be show blinking on line 2, that would be great.

| Button | Action                             | Function            |
|:-------|:-----------------------------------|:--------------------|
| Menu   | Switch to state 20x.               | Abandon Edit        | 
| Edit   | Save Data.<br>Switch to state 20x. | Save Edit           |
| Up     | switch to next menu item _value_   | Next Item Value     |
| Down   | switch to prior menu item _value_  | Previous Item Value |


## Configuration Options accessible from the menu.

Access Point Mode: Access Point or Station
Restart Mode: Yes or No


