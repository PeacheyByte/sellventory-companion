# main.py
import tkinter as tk
from ui import SellventoryApp

def main():
    root = tk.Tk()
    app = SellventoryApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()
