# main.py
import tkinter as tk
from ui import SellventoryApp

def main():
    root = tk.Tk()
    app = SellventoryApp(root)
    # Force the title after the app finishes initializing (overrides any later set)
    root.after_idle(lambda: root.title("The Collection Curator Companion"))
    root.mainloop()


if __name__ == "__main__":
    main()
