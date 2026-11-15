"""Scoped wheel scrolling without changing a closed combobox accidentally."""
import tkinter as tk
from tkinter import ttk

def install_wheel(canvas):
    tag='YangNingWheel_'+str(canvas)
    def scroll(event):
        if isinstance(event.widget,(tk.Text,ttk.Treeview,tk.Listbox)):return
        number=getattr(event,'num',None);delta=getattr(event,'delta',0)
        if number==4:units=-3
        elif number==5:units=3
        elif delta:units=(-1 if delta>0 else 1)*max(1,abs(int(delta))//120)*3
        else:return
        try:
            a,b=canvas.yview()
            if b-a<.999:canvas.yview_scroll(units,'units')
        except tk.TclError:return
        # This tag runs before the widget class binding. In particular a closed
        # speed/font combobox must not interpret scrolling as a value change.
        return 'break'
    for event in ('<MouseWheel>','<Button-4>','<Button-5>'):canvas.bind_class(tag,event,scroll)
    def add(widget):
        tags=list(widget.bindtags())
        if tag not in tags:widget.bindtags((tags[0],tag,*tags[1:]))
        for child in widget.winfo_children():add(child)
    add(canvas)
    def cleanup(event):
        if event.widget!=canvas:return
        for name in ('<MouseWheel>','<Button-4>','<Button-5>'):
            try:canvas.unbind_class(tag,name)
            except tk.TclError:pass
    canvas.bind('<Destroy>',cleanup,add='+')
