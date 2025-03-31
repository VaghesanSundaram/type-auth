import time
from pynput import keyboard
import threading

text = []
keyphrase = "hello"

def on_key_press(key): 
    try:
        text.append(key.char)
        print(key)
    except AttributeError:
        text.append(str(key))
    
    

def on_key_release(key):
    print(text)

def check():
    global text
    while True:
        if len(text) == len(keyphrase):
            if text == ['h','e','l','l','o']:
                print("Correct!")
                text = []
            else:
                print("Nope")
                text = []



my_thread = threading.Thread(target=check)
my_thread.start()

with keyboard.Listener(on_press = on_key_press, on_release=on_key_release) as press_listener:
    press_listener.join()
    
    my_thread.join()