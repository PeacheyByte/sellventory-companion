import tkinter as tk
from tkinter import messagebox

class SellventoryApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Sellventory Companion")
        self.root.geometry("600x400")

        # Menu bar
        menubar = tk.Menu(root)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Open Database", command=self.open_db)
        file_menu.add_command(label="Exit", command=root.quit)
        menubar.add_cascade(label="File", menu=file_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="About", command=self.show_about)
        menubar.add_cascade(label="Help", menu=help_menu)

        root.config(menu=menubar)

        # Main label
        label = tk.Label(root, text="Welcome to Sellventory Companion!", font=("Arial", 16))
        label.pack(pady=50)

    def open_db(self):
        messagebox.showinfo("Open Database", "This will open the Sellventory database (feature coming soon).")

    def show_about(self):
        messagebox.showinfo("About", "Sellventory Companion App\nVersion 0.1")

if __name__ == "__main__":
    root = tk.Tk()
    app = SellventoryApp(root)
    root.mainloop()
