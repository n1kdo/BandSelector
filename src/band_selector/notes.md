implement message queue.
  messages drive actions

  message types

  buttons 1-4 falling edge: control UI functions.
  pwrsense change.  can choose to turn on radio.
  band change.  send to band logic
  http responses -- valid
    band request responses
    information request responses
  http responses -- failures
    timeout or unreachable
  update display, write, home, clear, moveto, cursor on/off, value up/down?
  timer event



implement task that reads hardware inputs:
* buttons 1-4 -- either edge
* PWRSENSE -- either edge
* band data b0-b3 collectively as 4-bit value 0-F -- send event on edge
send message into message queue

implement task that runs async http transaction
enqueues result

implement task (?) to update display?  
do I need this?  all fast except clear and home, they need 5 ms.


Make the message a tuple.  in many cases, the message will be a 1-tuple, if 
there is such a thing.  In other cases, additional data may be references by
2nd (and subsequent) tuple values.

messages by ID:

1, 2, 3, 4: button ID, 2nd part of tuple is hi/lo
10: pwrsense, 2nd value is hi/lo
20-2x: network status messages, (code, text) -- is this used?
50: network down/up message, (50, 0|1)  **NOT USED**

90, 91, write LCD line 0,1 (9x,text)
100: band change, 2nd value is new band #
201 api status response, text in 2nd value of tuple
202 api select antenna, text in 2nd value of tuple
1000+: timer events.  