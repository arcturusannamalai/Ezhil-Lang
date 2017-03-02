#!/usr/bin/env python
##This Python file uses the following encoding: utf-8
##
## (C) 2016-2017 Muthiah Annamalai,
## Licensed under GPL Version 3
##
from __future__ import print_function
import codecs
import sys
import os
import gi
import ezhil
import tempfile
import threading
import multiprocessing
import time

PYTHON3 = (sys.version[0] == '3')
if PYTHON3:
    unicode = str

gi.require_version('Gtk','3.0')

from gi.repository import Gtk, GObject, GLib, Pango
from undobuffer import UndoableBuffer;

# Class from http://python-gtk-3-tutorial.readthedocs.io/en/latest/textview.html?highlight=textbuffer
class SearchDialog(Gtk.Dialog):
    def __init__(self, parent, text=u""):
        Gtk.Dialog.__init__(self, u"தேடு", parent,
            Gtk.DialogFlags.MODAL, buttons=(
            Gtk.STOCK_FIND, Gtk.ResponseType.OK,
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL))
        
        box = self.get_content_area()
        
        label = Gtk.Label(u"உரையில் தேட வேண்டிய சொல்லை இங்கு இடுக:")
        box.add(label)
        
        self.entry = Gtk.Entry()
        self.entry.set_text(text)
        box.add(self.entry)
        self.show_all()
        
    def get_query(self):
        return self.entry.get_text()

class Tokenizer:
    # given a piece of text figure out if it is a number, string-literal or
    # a keyword or just plain old text
    def __init__(self):
        self.lexer = ezhil.EzhilLex()
        
    def tokenize(self,chunk):
        self.lexer.reset()
        self.lexer.tokenize(chunk)
        self.lexer.tokens.reverse()
        return self.lexer.tokens

class EditorState:
    def __init__(self):
        # Gtk builder objects
        self.builder = Gtk.Builder()

        # timing logger
        self.tstart = 0.0
        self.tend = 0.0
        
        # editor Gtk widgets
        self.window = None
        self.abt_menu = None
        self.exit_btn = None
        self.MenuBar = None
        self.StatusBar = None
        self.textview = None
        self.textbuffer = None
        self.console_textview = None
        self.console_textbuffer = None
        self.sw = None

        # pure editor state
        self.filename = os.path.join(u'examples',u'untitled.n')
        self.file_modified = False
        self.count = 0
        
        # cosmetics
        self.TitlePrefix = u" -சுவடு எழுதி"
        
    # was editor code modified ?
    def is_edited(self):
        return self.textbuffer.get_modified()
    
    # editor code info
    def get_doc_info(self):
        r = {'line_count':0,'char_count':0,'modified':False}
        #print(dir(self.textbuffer))
        #print(self.textbuffer)
        r['line_count'] = self.textbuffer.get_line_count()
        r['char_count'] = self.textbuffer.get_char_count()
        r['modified'] = self.is_edited()
        return r

def MPRunner_actor(pipe,filename):
    is_success = False
    ezhil.EzhilCustomFunction.set(Editor.dummy_input)
    old_stdin = sys.stdin
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    tmpfilename = tempfile.mktemp()+".n"
    res_std_out = u""
    old_exit = sys.exit
    sys.exit = Editor.dummy_exit
    try:
        sys.stdout = codecs.open(tmpfilename,"w","utf-8")
        sys.stderr = sys.stdout;
        executer = ezhil.EzhilFileExecuter(filename)
        executer.run()
        is_success = True
    except Exception as e:
        print(u" '{0}':\n{1}'".format(filename, unicode(e)))
    finally:
        sys.exit = old_exit
        sys.stdout.flush()
        sys.stdout.close()
        with codecs.open(tmpfilename,u"r",u"utf-8") as fp:
            res_std_out = fp.read()
        sys.stdout = old_stdout
        sys.stderr = old_stderr
        sys.stdin = old_stdin
    pipe.send([ res_std_out,is_success] )
    pipe.close()

class MPRunner:
    is_success = False
    def __init__(self,timeout=150):
        self.timeout = timeout

    @staticmethod
    def update_fcn(args):
        res_std_out,is_success=args
        ed = Editor.get_instance()
        ed.tend = time.time()
        time_desc = u" %0.3g வினாடி"%(ed.tend - ed.tstart)
        ed.console_buffer.set_text( res_std_out )
        tag = is_success and ed.tag_pass or ed.tag_fail
        start = ed.console_buffer.get_start_iter()
        end = ed.console_buffer.get_end_iter()
        ed.console_buffer.apply_tag(tag,start,end)
        ed.StatusBar.push(0,u"உங்கள் நிரல் '%s' %s %s நேரத்தில் இயங்கி முடிந்தது"%(ed.filename,[u"பிழை உடன்",u"பிழையில்லாமல்"][is_success],time_desc))
        return

    def run(self,filename):
        ed = Editor.get_instance()
        if ( ed.is_edited() ):
            #document is edited but not saved;
            msg = u"உங்கள் நிரல் சேமிக்க பட வேண்டும்! அதன் பின்னரே இயக்கலாம்"
            title = u"இயக்குவதில் பிழை"
            dialog = Gtk.MessageDialog(ed.window, 0, Gtk.MessageType.INFO,
            Gtk.ButtonsType.OK, title) #"Output of Ezhil Code:"
            dialog.format_secondary_text(msg) #res.std_out
            dialog.run()
            dialog.destroy() #OK or Cancel don't matter
            return False

        # Start bar as a process
        parent_conn, child_conn = multiprocessing.Pipe()
        ed.tstart = time.time()
        p = multiprocessing.Process(target=MPRunner_actor,args=([child_conn,filename]))
        p.start()
        child_conn.close()
        if parent_conn.poll(self.timeout):
            res_std_out, is_success = parent_conn.recv()
            p.join(0)
            parent_conn.close()
        elif p.is_alive():
            #print("running... let's kill it...")
            # Terminate
            p.terminate()
            p.join()
            is_success = False
            res_std_out = u"timeout %g(s) reached - program taking too long\n"%self.timeout
        else:
            is_success = False
            res_std_out = u"unknown!"
        GLib.idle_add( MPRunner.update_fcn, [ res_std_out,is_success ])
        return

class GtkStaticWindow:
    _instance = None
    @staticmethod
    def get_instance():
        if not GtkStaticWindow._instance:
            GtkStaticWindow._instance = GtkStaticWindow()
        return GtkStaticWindow._instance

    def __init__(self):
        self.gui = threading.Thread(target=lambda : Gtk.main_iteration())
        self.window = Gtk.Window(Gtk.WindowType.TOPLEVEL)
        self.window.set_default_size(50,20) #vanishingly small size
        self.window.connect("delete-event", Gtk.main_quit)
        self.window.set_title(u"Child process window")
        self.window.set_decorated(False)
        self.window.show_all()
        self.gui.start()

class Editor(EditorState):
    _instance = None
    def __init__(self,filename=None):
        EditorState.__init__(self)
        Editor._instance = self
        self.builder.add_from_file("res/editor.glade")
        if filename:
            self.filename = filename
        ## construct the GUI from GLADE
        self.window = self.builder.get_object("ezhilEditorWindow")
        self.set_title()
        self.window.set_resizable(True)
        self.window.set_position(Gtk.WindowPosition.CENTER_ALWAYS)
        self.console_textview = self.builder.get_object("codeExecutionTextView")
        #self.console_textview.set_editable(False)
        self.console_textview.set_cursor_visible(False)
        self.console_textview.set_buffer(UndoableBuffer())
        self.console_buffer = self.console_textview.get_buffer()
        self.scrolled_codeview = self.builder.get_object("scrolledwindow1")
        self.textview = self.builder.get_object("codeEditorTextView")
        self.StatusBar = self.builder.get_object("editorStatus")
        self.textview.set_buffer(UndoableBuffer())
        self.textbuffer = self.textview.get_buffer()
        self.scrolled_codeview.set_policy(Gtk.PolicyType.AUTOMATIC,Gtk.PolicyType.AUTOMATIC)
        # comment purple
        # keywords orange
        # text black
        # literal green
        self.tag_comment  = self.textbuffer.create_tag("comment",
            weight=Pango.Weight.SEMIBOLD,foreground="red")
        self.tag_keyword  = self.textbuffer.create_tag("keyword",
            weight=Pango.Weight.BOLD,foreground="blue")
        self.tag_literal  = self.textbuffer.create_tag("literal",
            style=Pango.Style.ITALIC,foreground="green")
        self.tag_operator = self.textbuffer.create_tag("operator",
            weight=Pango.Weight.SEMIBOLD,foreground="olive")
        self.tag_text = self.textbuffer.create_tag("text",foreground="black")
        self.tag_found = self.textbuffer.create_tag("found",
            background="yellow")
                
        # for console buffer
        self.tag_fail  = self.console_buffer.create_tag("fail",
            weight=Pango.Weight.SEMIBOLD,foreground="red")
        self.tag_pass  = self.console_buffer.create_tag("pass",
            weight=Pango.Weight.SEMIBOLD,foreground="green")
        
        # connect abt menu and toolbar item
        self.abt_menu = self.builder.get_object("aboutMenuItem")
        self.abt_menu.connect("activate",Editor.show_about_status)
        
        self.abt_btn = self.builder.get_object("AboutBtn")
        self.abt_btn.connect("clicked",Editor.show_about_status)

        paste_menu = self.builder.get_object("paste_item")
        paste_menu.connect("activate",Editor.paste_action)

        cp_menu = self.builder.get_object("copy_item")
        cp_menu.connect("activate",Editor.copy_action)
        
        # for code textview
        #self.textview.connect("backspace",Editor.on_codebuffer_edited)
        #self.textview.connect("delete-from-cursor",Editor.on_codebuffer_edited)
        #self.textview.connect("insert-at-cursor",Editor.on_codebuffer_edited)
        
        # search action in text buffer
        search_menu = self.builder.get_object("search_item")
        search_menu.connect("activate",Editor.on_search_clicked)
        
        # open : editor action
        self.open_menu = self.builder.get_object("openMenuItem")
        self.open_menu.connect("activate",Editor.open_file)
        self.open_btn = self.builder.get_object("OpenBtn")
        self.open_btn.connect("clicked",Editor.open_file)

        # new : editor action
        self.new_menu = self.builder.get_object("newMenuItem")
        self.new_menu.connect("activate",Editor.reset_new)
        self.new_btn = self.builder.get_object("NewBtn")
        self.new_btn.connect("clicked",Editor.reset_new)
        
        # run : editor action
        self.run_menu = self.builder.get_object("runMenuItem")
        self.run_menu.connect("activate",Editor.run_ezhil_code)
        self.run_btn = self.builder.get_object("RunBtn")
        self.run_btn.connect("clicked",Editor.run_ezhil_code)
        
        # save : editor action save
        self.save_btn = self.builder.get_object("SaveBtn")
        self.save_btn.connect("clicked",Editor.save_file)
        
        # clear buffer : clear run buffer
        self.clear_btn = self.builder.get_object("clearbuffer")
        self.clear_btn.connect("clicked",Editor.clear_buffer)
        
        # hookup the exit
        self.exit_btn = self.builder.get_object("ExitBtn")
        self.exit_btn.connect("clicked",Editor.exit_editor)
        self.exit_menu = self.builder.get_object("quitMenuItem")
        self.exit_menu.connect("activate",Editor.exit_editor)
        # exit by 'x' btn
        self.window.connect("destroy",Editor.exit_editor)
        self.window.show_all()
        
        self.load_file()
        Gtk.main()
    
    # update title
    def set_title(self):
        self.window.set_title(self.filename + self.TitlePrefix)

    def apply_comment_syntax_highlighting(self,c_line):
        syntax_tag = self.tag_comment
        self.textbuffer.insert_at_cursor( c_line )
        self.textbuffer.insert_at_cursor("\n")
        n_end = self.textbuffer.get_end_iter()
        n_start = self.textbuffer.get_iter_at_offset(self.textbuffer.get_char_count()-1-len(c_line))
        self.textbuffer.apply_tag(syntax_tag,n_start,n_end)

    # todo - at every keystroke we need to run the syntax highlighting
    @staticmethod
    def on_codebuffer_edited(*args):
        ed = Editor.get_instance()
        mrk_start = ed.textbuffer.get_insert()
        m_start = ed.textbuffer.get_iter_at_mark(mrk_start)
        mrk_end = ed.textbuffer.get_insert()
        m_end = ed.textbuffer.get_iter_at_mark(mrk_end)
        m_end.forward_line()
        while not m_start.starts_line():
            m_start.backward_char()
        text = ed.textbuffer.get_text(m_start,m_end,True)
        try:
            ed.run_syntax_highlighting(text,[m_start,m_end])
        except Exception as e:
            ed.textbuffer.set_text(m_start,m_end,text)
            print(u"skip exception %s"%e)
        return False #callback was not handled AFAIK

    def run_syntax_highlighting(self,text,bounds=None):
        EzhilToken = ezhil.EzhilToken
        if not bounds:
            start,end = self.textbuffer.get_bounds()
        else:
            start,end = bounds
        
        self.textbuffer.delete(start,end)
        lines = text.split(u"\n")
        lexer = Tokenizer()
        for line in lines:
            comment_line = line.strip()
            if comment_line.startswith(u"#"):
                self.apply_comment_syntax_highlighting(comment_line)
                continue
            idx_comment_part = comment_line.find("#")
            if idx_comment_part != -1:
                line_alt = comment_line[0:idx_comment_part]
                comment_line = comment_line[idx_comment_part:]
            else:
                line_alt = line
                comment_line = None
            line = line_alt
            lexemes = lexer.tokenize(line)
            for lexeme in lexemes:
                is_string = False
                tok = lexeme.kind
                is_keyword = False
                if unicode(lexeme.val) in [u"உள்ளடக்கு",u"பின்கொடு",u"பதிப்பி",u"ஒவ்வொன்றாக",u"@",u"இல்"] \
                        or EzhilToken.is_keyword(tok):
                    is_keyword = True
                    syntax_tag = self.tag_keyword
                elif EzhilToken.is_id(tok):
                    syntax_tag = self.tag_operator
                elif EzhilToken.is_number(tok):
                    syntax_tag = self.tag_literal
                elif EzhilToken.is_string(tok):
                    is_string = True
                    syntax_tag = self.tag_literal
                else:
                    syntax_tag = self.tag_text
                m_start = self.textbuffer.get_insert()

                if is_keyword:
                     lexeme_val = lexeme.val + u" "
                elif EzhilToken.is_number(lexeme.kind):
                    lexeme_val = unicode(lexeme.val)
                elif is_string:
                     lexeme_val = u"\""+lexeme.val.replace("\n","\\n")+u"\""
                else:
                     lexeme_val = lexeme.val
                self.textbuffer.insert_at_cursor( lexeme_val )
                n_end = self.textbuffer.get_end_iter()
                n_start = self.textbuffer.get_iter_at_offset(self.textbuffer.get_char_count()-len(lexeme_val))
                self.textbuffer.apply_tag(syntax_tag,n_start,n_end)
                #self.textbuffer.insert_at_cursor(u" ")
            if comment_line:
                self.apply_comment_syntax_highlighting(u" "+comment_line)
                continue
            self.textbuffer.insert_at_cursor(u"\n")

    @staticmethod
    def clear_buffer(menuitem,arg1=None):
        ed = Editor.get_instance()
        ed.console_buffer.set_text(u"")
        ed.StatusBar.push(0,u"Evaluate buffer cleared")
    
    @staticmethod
    def reset_new(menuitem,arg1=None):
        ed = Editor.get_instance()
        ed.count += 1
        ed.filename = u"untitled_%d"%ed.count
        ed.set_title()
        ed.textbuffer = ed.textview.get_buffer()
        ed.textbuffer.set_text("")
        ed.textbuffer.set_modified(False)
        ed.console_buffer = ed.console_textview.get_buffer()
    
    @staticmethod
    def alert_dialog(title,msg,use_ok_cancel=False):
        ed = Editor.get_instance()
        if use_ok_cancel:
            dialog = Gtk.MessageDialog(ed.window, 0, Gtk.MessageType.QUESTION,
                              Gtk.ButtonsType.OK_CANCEL, title)
        else:
            dialog = Gtk.MessageDialog(ed.window, 0, Gtk.MessageType.INFO,
            Gtk.ButtonsType.OK, title) #"Output of Ezhil Code:"
        dialog.format_secondary_text(msg) #res.std_out
        response = dialog.run()
        dialog.destroy() #OK or Cancel don't matter
        return response

    @staticmethod
    def copy_action(*args_ign):
        ed = Editor.get_instance()
        bounds = ed.textbuffer.get_selection_bounds()
        clipboard = Gtk.Clipboard.get_default( ed.window.get_display() )
        text = ed.textbuffer.get_text(bounds[0],bounds[1],True)
        clipboard.set_text(text,len(text))
        
    @staticmethod
    def paste_action(*args_ign):
        ed = Editor.get_instance()
        clipboard = Gtk.Clipboard.get_default( ed.window.get_display() )
        clipboard.request_text(ed.readclipboard, user_data=None)
		
    #callback for clipboard paste
    def readclipboard(self, clipboard, text, data):
        self.textbuffer.insert_at_cursor(text,len(text))
    
    @staticmethod
    def dummy_exit(*args):
        #(u"Dummy exit function")
        return 0
    
    @staticmethod
    def dummy_input(*args):
        message= not args and "Enter Input" or args[0]
        if not args or len(args) < 2:
            title = "Ezhil language IDE"
        else:
            title = args[1]
        static_window = GtkStaticWindow.get_instance()
        window = static_window.window
        dialogWindow = Gtk.MessageDialog(window,
                              Gtk.DialogFlags.MODAL,
                              Gtk.MessageType.QUESTION,
                              Gtk.ButtonsType.OK_CANCEL,
                              message)

        dialogWindow.set_title(title)

        dialogBox = dialogWindow.get_content_area()
        userEntry = Gtk.Entry()
        userEntry.set_size_request(257,0)
        dialogBox.pack_end(userEntry, False, False, 0)
        dialogWindow.show_all()
        response = dialogWindow.run()
        text = userEntry.get_text() 
        dialogWindow.destroy()
        if (response == Gtk.ResponseType.OK) and (text != ''):
            return text
        return ""
    
    @staticmethod
    def run_ezhil_code(menuitem,arg1=None):
        ed = Editor.get_instance()
        runner = MPRunner()
        GLib.idle_add( lambda :  Gtk.main_iteration())
        runner.run(ed.filename)
        return
    
    @staticmethod
    def save_file(menuitem,arg1=None):
        ed = Editor.get_instance()
        textbuffer = ed.textview.get_buffer()
        
        if ed.filename.find("untitled") >= 0:        
            dialog = Gtk.FileChooserDialog("நிரலை சேமிக்கவும்:", ed.window,
                Gtk.FileChooserAction.SAVE,
                (Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                 Gtk.STOCK_SAVE, Gtk.ResponseType.OK))
            Editor.add_filters(dialog)
            response = dialog.run()
            if response == Gtk.ResponseType.CANCEL:
                dialog.destroy()
                #print("Dismiss save dialog - not saved!")
                return
            if dialog.get_filename():
                ed.filename = dialog.get_filename()
            dialog.destroy()
        if ed.filename is not "":
            textbuffer = ed.textview.get_buffer()
        filename = ed.filename
        #print("Saved File: " + filename)
        ed.StatusBar.push(0,"Saved File: " + filename)
        index = filename.replace("\\","/").rfind("/") + 1
        text = textbuffer.get_text(textbuffer.get_start_iter() , textbuffer.get_end_iter(),True)
        ed.window.set_title(filename[index:] + ed.TitlePrefix)
        try:
            with codecs.open(filename, "w","utf-8") as file:
                file.write(PYTHON3 and text or text.decode("utf-8"))
                file.close()
        except IOError as ioe:
            # new file:
            with codecs.open(filename, "w","utf-8") as file:
                file.write(PYTHON3 and text or text.decode("utf-8"))
                file.close()
        textbuffer.set_modified(False)
        return
    
    ## open handler
    @staticmethod
    def open_file(menuitem, arg1=None):
        textview = Editor.get_instance().textview
        Window = Editor.get_instance().window
        StatusBar = Editor.get_instance().StatusBar

        textbuffer = textview.get_buffer()
        chooser = Gtk.FileChooserDialog("நிரலை திறக்கவும்:", Window,
        Gtk.FileChooserAction.OPEN,(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OPEN, Gtk.ResponseType.OK))
        Editor.add_filters(chooser)
        textbuffer.set_modified(False)
        response = chooser.run()
        if response == Gtk.ResponseType.OK:
            filename = chooser.get_filename()
            ed = Editor.get_instance()
            ed.filename = filename
            ed.load_file()
            chooser.destroy()
        elif response == Gtk.ResponseType.CANCEL:
            chooser.destroy()
        else:
            chooser.destroy()
        return
    
    def load_file(self):
        ed = Editor.get_instance()
        textview = Editor.get_instance().textview
        Window = Editor.get_instance().window
        StatusBar = Editor.get_instance().StatusBar
        filename = ed.filename
        textbuffer = textview.get_buffer()
        #print("Opened File: " + filename)
        StatusBar.push(0,"Opened File: " + filename)
        #print("file =>",filename)
        Window.set_title(filename + u" - சுவடு எழுதி")
        try:
            text = u""
            with codecs.open(filename, "r","utf-8") as file:
                text = file.read()
        except IOError as ioe:
            Window.set_title(u"untitled.n - சுவடு எழுதி")
        #("Setting buffer to contents =>",text)
        textview.set_buffer(textbuffer)
        try:
            ed.run_syntax_highlighting(text)
        except Exception as slxe:
            StatusBar.push(0,u"இந்த நிரலை '%s', Syntax Highlighting செய்ய முடியவில்லை"%filename)
            textbuffer.set_text(text)
        textbuffer.set_modified(False)
        return
        
    @staticmethod
    def on_search_clicked(*args_to_ignore):
        ed = Editor.get_instance()
        # clear any previous tags in the space
        ed.textbuffer.remove_tag(ed.tag_found, \
                    ed.textbuffer.get_start_iter(), \
                    ed.textbuffer.get_end_iter())
        dialog = SearchDialog(ed.window)
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            cursor_mark = ed.textbuffer.get_insert()
            start = ed.textbuffer.get_iter_at_mark(cursor_mark)
            if start.get_offset() == ed.textbuffer.get_char_count():
                start = ed.textbuffer.get_start_iter()

            ed.search_and_mark(dialog.entry.get_text(), start)

        dialog.destroy()

    def search_and_mark(self, text, start):
        end = self.textbuffer.get_end_iter()
        match = start.forward_search(text, 0, end)

        if match != None:
            match_start, match_end = match
            self.textbuffer.apply_tag(self.tag_found, match_start, match_end)
            self.search_and_mark(text, match_end)

    ## miscellaneous signal handlers
    @staticmethod
    def exit_editor(exit_btn):
        ed = Editor.get_instance()
        if ed.is_edited():
            okcancel=True
            respo = Editor.alert_dialog(u"நிரலை சேமிக்கவில்லை",u"உங்கள் நிரல் மாற்றப்பட்டது; இதனை சேமியுங்கள்!",okcancel)
            if respo == Gtk.ResponseType.OK:
                Editor.save_file(None)
        Gtk.main_quit()
    
    @staticmethod
    def abt_dlg_closer(abt_dlg,event):
        abt_dlg.destroy()

    # About status dialog
    @staticmethod
    def show_about_status(*args):
        builder = Gtk.Builder()
        builder.add_from_file("res/editor.glade")
        abt_menu = args[0]
        abt_dlg = builder.get_object("ezhilAboutDialog")
        #Parent = builder.get_object("ezhilEditorWindow"))
        abt_dlg.show_all()
        ed = Editor.get_instance()
        print(ed.get_doc_info())
        close_btn = builder.get_object("aboutdialog-action_area1")
        abt_dlg.connect("response",Editor.abt_dlg_closer)
        return True

    # filters / utilities
    @staticmethod
    def add_filters(chooser):
        filter = Gtk.FileFilter()
        items = (("Ezhil Files","text/x-ezhil","*.n"),
        ("Text Files","text/data","*.txt"),
        ("All Files","text/data","*.*"))

        for data in items:
            name,mtype,patt = data
            filter = Gtk.FileFilter()
            filter.set_name(name)
            filter.add_mime_type(mtype)
            filter.add_pattern(patt)
            chooser.add_filter(filter)
        return

    # Singleton business
    @staticmethod
    def get_instance():
        return Editor._instance

    @staticmethod
    def set_instance(newinst):
        Editor._instance = newinst
        return Editor._instance

if __name__ == u"__main__":
    os.putenv('LANG','ta_IN.utf8')
    GObject.threads_init()
    Editor(len(sys.argv) > 1 and sys.argv[1] or None)
