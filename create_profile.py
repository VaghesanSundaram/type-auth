import time
from pynput import keyboard
import threading

text = []
keyphrase = "a"
def on_key_press(key): 
    text.append(key.char)
    print(key)
    

def on_key_release(key):
    print(text)

def check():
    if (len(text) == len(keyphrase)):
        if ("".join(text) != keyphrase):
            print("try again")
            text = []
            return
        else:
            print("done")
            quit()



my_thread = threading.Thread(target=check)
my_thread.start()
with keyboard.Listener(on_press = on_key_press, on_release=on_key_release) as press_listener:
    press_listener.join()

my_thread.join()