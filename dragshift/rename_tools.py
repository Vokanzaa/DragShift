"""A shared, preview-first bulk naming editor; file changes use their own undo."""
import csv
from dataclasses import replace
from pathlib import Path
import threading
import uuid

from PySide6.QtCore import QAbstractTableModel,QModelIndex,QStandardPaths,Qt,QTimer,Signal
from PySide6.QtWidgets import (QAbstractItemView,QCheckBox,QComboBox,QFileDialog,QFormLayout,
    QApplication,QHBoxLayout,QHeaderView,QLabel,QLineEdit,QListWidget,QListWidgetItem,QProgressBar,
    QPushButton,QSpinBox,QSplitter,QTableView,QVBoxLayout,QWidget)

from . import bulk_rename
from .gif_sequence import ordered_paths
from .i18n import tr
from .media_controls import DropZone
from .rename_rules import Rule,preset_json,read_preset
from .util import UserError
from .video_tools import _AsyncTools

KINDS={
 'insert':'Insert text','delete':'Delete characters','remove':'Remove text','replace':'Replace text',
 'regex':'Regular expression','case':'Letter case','number':'Numbering','padding':'Pad numbers',
 'strip':'Strip characters','clean':'Clean up names','translit':'Transliterate to Latin',
 'template':'Name template','rearrange':'Rearrange parts','date_reformat':'Reformat date',
 'random':'Random text','extension':'Change extension','mapping':'Filename mapping'}

# Field = option key, visible label, control type, default, choices or range.
FIELDS={
 'insert':[('text','Text','text','',None),('where','Position','choice','prefix',('prefix','suffix','position','before','after')),
           ('position','Character position (1 = first)','int',1,(1,4096)),('anchor','Match text','text','',None)],
 'delete':[('start','Character position (1 = first)','int',1,(1,4096)),('count','Characters to delete','int',1,(0,4096)),('from_right','Count from the right','bool',False,None)],
 'remove':[('text','Text to remove','text','',None),('count','Occurrences (0 = all)','int',0,(0,100000)),('case_sensitive','Match case','bool',True,None)],
 'replace':[('find','Find','text','',None),('replace','Replace with','text','',None),('count','Occurrences (0 = all)','int',0,(0,100000)),('case_sensitive','Match case','bool',True,None)],
 'regex':[('find','Expression','text','',None),('replace','Replacement (\\1 = group 1)','text','',None),('count','Occurrences (0 = all)','int',0,(0,100000)),('case_sensitive','Match case','bool',True,None)],
 'case':[('mode','Letter case','choice','lower',('lower','upper','title','sentence','swap'))],
 'number':[('start','Start number','int',1,(-1000000000,1000000000)),('step','Number step','int',1,(-1000000,1000000)),
           ('pad','Minimum digits','int',3,(0,12)),('where','Position','choice','suffix',('prefix','suffix','replace')),
           ('separator','Separator','text','_',None),('per_folder','Restart in each folder','bool',False,None)],
 'padding':[('width','Minimum digits','int',3,(0,12))],
 'strip':[('mode','Remove','choice','digits',('digits','symbols','brackets','spaces','characters')),('characters','Characters','text','',None)],
 'template':[('text','Template','text','{name}_{n:03}',None)],
 'rearrange':[('delimiter','Split at','text','_',None),('text','Template','text','{part2}_{part1}',None)],
 'date_reformat':[('find','Date expression','text',r'\d{4}-\d{2}-\d{2}',None),
                  ('input_format','Existing date format','text','%Y-%m-%d',None),('output_format','New date format','text','%d.%m.%Y',None)],
 'random':[('length','Text length','int',8,(1,32)),('where','Position','choice','suffix',('prefix','suffix','replace')),
           ('separator','Separator','text','_',None),('seed','Random seed','text','',None)],
 'extension':[('text','New extension','text','',None)],
}
CHOICES={'prefix':'Before name','suffix':'After name','position':'At character','before':'Before matching text',
 'after':'After matching text','replace':'Replace the name','lower':'lowercase','upper':'UPPERCASE',
 'title':'Title Case','sentence':'Sentence case','swap':'Swap case','digits':'Digits','symbols':'Punctuation / symbols',
 'brackets':'Brackets','spaces':'Whitespace','characters':'Specific characters',
 'stem':'Name only · keep extension','full':'Full filename','extension':'Extension only'}


class RenameDropZone(DropZone):
    def accepted(self,mime):
        # Unlike conversion, renaming a .lnk must never resolve its target.
        return [Path(url.toLocalFile()) for url in mime.urls() if url.isLocalFile()
                and (Path(url.toLocalFile()).is_file() or Path(url.toLocalFile()).is_dir())] if mime.hasUrls() else []


class RenameTable(QAbstractTableModel):
    selectionChanged=Signal(str,bool)
    nameEdited=Signal(str,str)
    def __init__(self,parent=None):
        super().__init__(parent);self.rows=[];self.excluded=set();self.editable=True;self.completed=False;self.overrides={}

    def rowCount(self,parent=QModelIndex()):return 0 if parent.isValid() else len(self.rows)
    def columnCount(self,parent=QModelIndex()):return 5

    def headerData(self,section,orientation,role=Qt.DisplayRole):
        if role==Qt.DisplayRole and orientation==Qt.Horizontal:return tr(('Use','Current name','New name','Status','Folder')[section])
        return super().headerData(section,orientation,role)

    def data(self,index,role=Qt.DisplayRole):
        if not index.isValid():return None
        entry=self.rows[index.row()];key=str(entry.source)
        if role==Qt.CheckStateRole and index.column()==0:return Qt.Unchecked if key in self.excluded else Qt.Checked
        if role in (Qt.DisplayRole,Qt.EditRole,Qt.ToolTipRole):
            status='Not selected' if key in self.excluded else entry.error or (('Renamed' if self.completed else 'Ready') if entry.source.name!=entry.target.name else 'Unchanged')
            return ('',entry.source.name,self.overrides.get(key,entry.target.name),tr(status),str(entry.source.parent))[index.column()]
        return None

    def flags(self,index):
        flags=super().flags(index)
        if self.editable and index.isValid():
            if index.column()==0:flags|=Qt.ItemIsUserCheckable
            if index.column()==2:flags|=Qt.ItemIsEditable
        return flags

    def setData(self,index,value,role=Qt.EditRole):
        if not self.editable or not index.isValid():return False
        entry=self.rows[index.row()]
        if index.column()==0 and role==Qt.CheckStateRole:
            enabled=value==Qt.Checked or value==Qt.Checked.value
            self.excluded.discard(str(entry.source)) if enabled else self.excluded.add(str(entry.source))
            self.dataChanged.emit(index,index)
            self.selectionChanged.emit(str(entry.source),enabled);return True
        if index.column()==2 and role==Qt.EditRole:
            self.overrides[str(entry.source)]=str(value);self.dataChanged.emit(index,index)
            self.nameEdited.emit(str(entry.source),str(value));return True
        return False

    def set_rows(self,rows,excluded,overrides=None,*,completed=False):
        self.beginResetModel();self.rows=list(rows);self.excluded=set(excluded);self.overrides=dict(overrides or {});self.completed=completed;self.endResetModel()


class BulkRenameWindow(_AsyncTools):
    renameProgress=Signal(int)
    tool_name='Rename'

    def __init__(self,paths,notify,*,journal_dir=None):
        super().__init__('Rename files',paths,notify,(1120,800))
        self.paths=list(dict.fromkeys(Path(p).parent.resolve()/Path(p).name for p in paths))
        self.rules=[];self.overrides={};self.excluded=set();self.plan=None
        self.revision=0;self.preview_busy=False;self.busy=False;self._editing=False;self.want_preview=False
        self.cancel=threading.Event();self.preview_cancel=threading.Event();self.last_journal=None
        self.review_journal=None
        self.journal_dir=Path(journal_dir) if journal_dir is not None else Path(QStandardPaths.writableLocation(QStandardPaths.GenericDataLocation))/'DragShift'/'rename-journals'
        self.drop=RenameDropZone('Drop files or folders here to add them')
        self.drop.setMaximumHeight(52);self.drop.setMinimumHeight(44)
        self.drop.filesDropped.connect(self.add_paths);self.body.addWidget(self.drop)
        toolbar=QHBoxLayout()
        self.action_buttons=[]
        for title,fn in [('Add files…',self.choose_files),('Add folder…',self.choose_folder),
                         ('Load rules…',self.load_rules),('Save rules…',self.save_rules),('Import CSV…',self.import_csv),('Export CSV…',self.export_csv)]:
            button=QPushButton(tr(title));button.clicked.connect(fn);toolbar.addWidget(button);self.action_buttons.append(button)
        self.body.addLayout(toolbar)
        top=QHBoxLayout()
        top.addWidget(QLabel(tr('Quick start')))
        self.quick=QComboBox()
        for title,key in [('Custom rules','custom'),('Number files','number'),('Add a prefix','prefix'),('Clean names','clean'),
                          ('Latin names','latin'),('Modified date + number','date')]:self.quick.addItem(tr(title),key)
        self.quick.currentIndexChanged.connect(self.use_quick)
        top.addWidget(self.quick)
        top.addStretch()
        top.addWidget(QLabel(tr('File order')))
        self.order=QComboBox()
        for label,value in [('Name · natural numbers','name'),('Modified date · oldest first','date'),('Added order','manual')]:self.order.addItem(tr(label),value)
        self.order.currentIndexChanged.connect(self.schedule_preview)
        top.addWidget(self.order)
        self.preview_button=QPushButton(tr('Preview names'));self.preview_button.clicked.connect(self.schedule_preview)
        top.addWidget(self.preview_button)
        self.body.addLayout(top)
        splitter=QSplitter(Qt.Horizontal)
        self.rules_pane=QWidget();left=QVBoxLayout(self.rules_pane);left.setContentsMargins(0,0,8,0)
        add=QHBoxLayout();self.kind=QComboBox()
        for key,title in KINDS.items():
            if key!='mapping':self.kind.addItem(tr(title),key)
        add.addWidget(self.kind,1)
        add_btn=QPushButton(tr('Add rule'));add_btn.clicked.connect(self.add_rule);add.addWidget(add_btn)
        left.addLayout(add)
        self.rule_list=QListWidget();self.rule_list.setMaximumHeight(145)
        self.rule_list.setAccessibleName(tr('Ordered rename rules'))
        self.rule_list.currentRowChanged.connect(self.select_rule);self.rule_list.itemChanged.connect(self.rule_enabled)
        left.addWidget(self.rule_list)
        buttons=QHBoxLayout()
        for title,fn in [('Move rule up',lambda:self.move_rule(-1)),('Move rule down',lambda:self.move_rule(1)),('Remove rule',self.remove_rule)]:
            button=QPushButton(tr(title));button.clicked.connect(fn);buttons.addWidget(button)
        left.addLayout(buttons)
        self.option_widget=QWidget();self.options_form=QFormLayout(self.option_widget)
        self.options_form.setContentsMargins(0,0,0,0)
        self.fields={};left.addWidget(self.option_widget)
        self.rule_hint=QLabel(tr('Rules run from top to bottom. Extensions stay unchanged unless you explicitly edit them.'))
        self.rule_hint.setWordWrap(True);left.addWidget(self.rule_hint);left.addStretch()
        splitter.addWidget(self.rules_pane)
        self.table=QTableView();self.model=RenameTable(self)
        self.table.setModel(self.model)
        self.table.setAccessibleName(tr('Rename preview · current and new filenames'))
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().hide()
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        for column,width in enumerate((60,210,230,180)):self.table.setColumnWidth(column,width)
        self.model.selectionChanged.connect(self.include_file)
        self.model.nameEdited.connect(self.override_name)
        splitter.addWidget(self.table);splitter.setSizes([330,760])
        self.body.addWidget(splitter,1)
        self.summary=QLabel();self.summary.setWordWrap(True);self.body.addWidget(self.summary)
        self.body.addWidget(self.error)
        self.progress=QProgressBar();self.progress.setRange(0,100);self.progress.hide()
        self.renameProgress.connect(self.progress.setValue);self.body.addWidget(self.progress)
        footer=QHBoxLayout()
        self.history=QComboBox();self.history.addItem(tr('Recent renames / recovery'),None)
        self.history.setAccessibleName(tr('Recent renames / recovery'));self.history.currentIndexChanged.connect(self.review_history)
        footer.addWidget(self.history)
        self.back=QPushButton(tr('Back to rules'));self.back.clicked.connect(self.leave_history);self.back.hide();footer.addWidget(self.back)
        self.undo_button=QPushButton(tr('Undo rename'));self.undo_button.setEnabled(False);self.undo_button.clicked.connect(self.undo_current);footer.addWidget(self.undo_button)
        footer.addStretch()
        self.cancel_button=QPushButton(tr('Close'));self.cancel_button.clicked.connect(self.cancel_or_close);footer.addWidget(self.cancel_button)
        self.apply_button=QPushButton(tr('Rename files'));self.apply_button.setObjectName('primary');self.apply_button.setEnabled(False)
        self.apply_button.clicked.connect(self.apply_names);footer.addWidget(self.apply_button)
        self.primary_btn=self.apply_button
        self.body.addLayout(footer)
        self.timer=QTimer(self,interval=180,singleShot=True,timeout=self.start_preview)
        self.schedule_preview()
        self.refresh_history()
        QApplication.instance().aboutToQuit.connect(self._cancel_all)

    def accepts_sources(self,paths):return bool(paths)
    def receive_files(self,paths):self.add_paths(paths)

    def dragEnterEvent(self,event):
        if not self.busy and self.drop.accepted(event.mimeData()):event.setDropAction(Qt.CopyAction);event.accept()
        else:event.ignore()

    def dragMoveEvent(self,event):self.dragEnterEvent(event)

    def dropEvent(self,event):
        paths=self.drop.accepted(event.mimeData())
        if paths and not self.busy:self.add_paths(paths);event.setDropAction(Qt.CopyAction);event.accept()
        else:event.ignore()

    def add_paths(self,paths):
        if self.busy:return
        if self.review_journal:self.leave_history()
        self.paths=list(dict.fromkeys([*self.paths,*(Path(p).parent.resolve()/Path(p).name for p in paths)]))
        self.schedule_preview()

    def choose_files(self):
        paths,_=QFileDialog.getOpenFileNames(self,tr('Add files'),'',tr('All files (*)'),options=QFileDialog.DontResolveSymlinks)
        self.add_paths(paths)

    def choose_folder(self):
        path=QFileDialog.getExistingDirectory(self,tr('Add folder'),options=QFileDialog.DontResolveSymlinks)
        if path:self.add_paths([path])

    def set_rules(self,rules):
        self.rules=list(rules);self.refresh_rule_list(0);self.schedule_preview()

    def use_quick(self):
        key=self.quick.currentData()
        choices={'number':[Rule('number',{'where':'replace','pad':3})],
            'prefix':[Rule('insert',{'text':'prefix_'})],'clean':[Rule('clean')],'latin':[Rule('translit')],
            'date':[Rule('template',{'text':'{modified:%Y-%m-%d}_{n:03}'})]}
        if key in choices:self.set_rules(choices[key])

    def refresh_rule_list(self,index=None):
        self._editing=True
        if index is None:index=self.rule_list.currentRow()
        self.rule_list.clear()
        for number,rule in enumerate(self.rules):
            item=QListWidgetItem(f'{number+1}. '+tr(KINDS[rule.kind]))
            item.setFlags(item.flags()|Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if rule.enabled else Qt.Unchecked)
            self.rule_list.addItem(item)
        self._editing=False
        self.rule_list.setCurrentRow(min(max(0,index),len(self.rules)-1))
        self.select_rule(self.rule_list.currentRow())

    def add_rule(self):
        if len(self.rules)>=64:self.error.setText(tr('Use up to 64 rename rules.'));return
        kind=self.kind.currentData()
        options={key:default for key,_,_,default,_ in FIELDS.get(kind,[])}
        if kind=='random':options['seed']=uuid.uuid4().hex[:12]
        self.rules.append(Rule(kind,options));self.refresh_rule_list(len(self.rules)-1);self.schedule_preview()

    def move_rule(self,delta):
        index=self.rule_list.currentRow();target=index+delta
        if 0<=index<len(self.rules) and 0<=target<len(self.rules):
            self.rules[index],self.rules[target]=self.rules[target],self.rules[index]
            self.refresh_rule_list(target);self.schedule_preview()

    def remove_rule(self):
        index=self.rule_list.currentRow()
        if 0<=index<len(self.rules):
            del self.rules[index];self.refresh_rule_list(index);self.schedule_preview()

    def rule_enabled(self,item):
        if self._editing:return
        index=self.rule_list.row(item)
        self.rules[index]=replace(self.rules[index],enabled=item.checkState()==Qt.Checked)
        self.schedule_preview()

    def select_rule(self,index):
        self._editing=True
        while self.options_form.rowCount():self.options_form.removeRow(0)
        self.fields={}
        if not 0<=index<len(self.rules):self._editing=False;return
        rule=self.rules[index]
        for key,label,kind,default,extra in FIELDS.get(rule.kind,[]):
            value=rule.options.get(key,default)
            if kind=='text':
                control=QLineEdit(str(value));control.setMaxLength(4096);signal=control.textEdited
            elif kind=='int':
                control=QSpinBox();control.setRange(*extra);control.setValue(value);control.setKeyboardTracking(False);signal=control.valueChanged
            elif kind=='bool':
                control=QCheckBox();control.setChecked(bool(value));signal=control.toggled
            else:
                control=QComboBox()
                for choice in extra:control.addItem(tr(CHOICES.get(choice,choice)),choice)
                control.setCurrentIndex(max(0,control.findData(value)));signal=control.currentIndexChanged
            control.setAccessibleName(tr(label));self.options_form.addRow(tr(label),control)
            self.fields[key]=control;signal.connect(self.update_rule)
        if rule.kind not in ('extension','mapping'):
            scope=QComboBox()
            for key in ('stem','full','extension'):scope.addItem(tr(CHOICES[key]),key)
            scope.setCurrentIndex(scope.findData(rule.scope));scope.currentIndexChanged.connect(self.update_rule)
            scope.setAccessibleName(tr('Apply to'));self.options_form.addRow(tr('Apply to'),scope);self.fields['scope']=scope
        hint=('Template fields: {name}, {ext}, {n:03}, {parent}, {modified:%Y-%m-%d}, {width}, {height}, {date_taken:%Y-%m-%d}, {artist}.'
              if rule.kind in ('insert','template','rearrange') else
              'Changing an extension only changes its name; it does not convert the file.' if rule.kind=='extension' else
              'Edit the new-name column or import a CSV mapping.' if rule.kind=='mapping' else
              'Rules run from top to bottom. Extensions stay unchanged unless you explicitly edit them.')
        self.rule_hint.setText(tr(hint));self._editing=False
        self.field_visibility(rule)

    def field_visibility(self,rule):
        if rule.kind=='insert':
            where=rule.options.get('where','prefix')
            for key,on in (('position',where=='position'),('anchor',where in ('before','after'))):
                if key in self.fields:self.options_form.setRowVisible(self.fields[key],on)
        if rule.kind=='strip' and 'characters' in self.fields:
            self.options_form.setRowVisible(self.fields['characters'],rule.options.get('mode')=='characters')

    def update_rule(self,*_):
        if self._editing:return
        index=self.rule_list.currentRow()
        if not 0<=index<len(self.rules):return
        old=self.rules[index];options=dict(old.options)
        scope=old.scope
        for key,control in self.fields.items():
            value=control.text() if isinstance(control,QLineEdit) else control.value() if isinstance(control,QSpinBox) else control.isChecked() if isinstance(control,QCheckBox) else control.currentData()
            if key=='scope':scope=value
            else:options[key]=value
        self.rules[index]=Rule(old.kind,options,scope,old.enabled)
        self.field_visibility(self.rules[index]);self.schedule_preview()

    def include_file(self,path,on):
        self.excluded.discard(path) if on else self.excluded.add(path)
        self.schedule_preview()

    def override_name(self,path,name):
        self.overrides[path]=name;self.schedule_preview()

    def schedule_preview(self,*_):
        if self.busy or self.review_journal:return
        self.want_preview=True;self.revision+=1;self.preview_cancel.set();self.apply_button.setEnabled(False)
        self.timer.start()

    def start_preview(self):
        if self.busy or self.review_journal:return
        if self.preview_busy:return
        self.want_preview=False
        self.preview_busy=True;self.preview_cancel=threading.Event()
        cancel=self.preview_cancel;revision=self.revision
        paths=list(self.paths);rules=list(self.rules);overrides=dict(self.overrides);excluded=set(self.excluded)
        order=self.order.currentData()
        self.summary.setText(tr('Preparing filename preview…'))
        def work():
            all_paths=ordered_paths(paths,order)
            plan=bulk_rename.preview([p for p in all_paths if str(p) not in excluded],rules,
                                     order='manual',overrides=overrides,cancel=cancel)
            active={str(entry.source):entry for entry in plan.entries}
            return plan,[active.get(str(p),bulk_rename.Entry(p,p,())) for p in all_paths]
        def finish(value=None,error=None):
            self.preview_busy=False
            if revision!=self.revision:
                if self.want_preview and not self.busy:self.timer.start(0)
                return
            if error:self.error.setText(tr(error));self.summary.setText(tr('Preview could not be prepared.'));return
            self.plan,rows=value;self.model.editable=True;self.model.set_rows(rows,excluded,overrides)
            self.error.setText(tr(self.plan.errors[0]) if self.plan.errors else '')
            self.summary.setText(tr('{0} selected · {1} names change · {2} errors. No files changed yet.').format(len(self.plan.entries),len(self.plan.changed),len(self.plan.errors)))
            self.apply_button.setEnabled(bool(self.plan.changed) and not self.plan.errors)
        self.lookup(work,finish,lambda error:finish(error=error))

    def _set_busy(self,busy):
        self.busy=busy;self.rules_pane.setEnabled(not busy);self.model.editable=not busy
        self.quick.setEnabled(not busy);self.order.setEnabled(not busy);self.drop.setEnabled(not busy)
        self.history.setEnabled(not busy);self.back.setEnabled(not busy);self.preview_button.setEnabled(not busy)
        for button in self.action_buttons:button.setEnabled(not busy)
        self.apply_button.setEnabled(False);self.undo_button.setEnabled(not busy and self.last_journal is not None)
        self.progress.setVisible(busy);self.progress.setValue(0)
        self.cancel_button.setText(tr('Cancel' if busy else 'Close'))

    def run_rename(self,fn,*,undoing=False,recovering=False):
        self.revision+=1;self.want_preview=False;self.timer.stop();self.preview_cancel.set();self.cancel=threading.Event();self._set_busy(True)
        self.cancel_button.setEnabled(not recovering)
        self.error.clear()
        def finish(result=None,error=None):
            self._set_busy(False);self.cancel_button.setEnabled(True)
            if error:self.error.setText(tr(error));self.refresh_history();return
            mapping={str(old):new for old,new in result.pairs}
            self.paths=[mapping.get(str(path),path) for path in self.paths]
            self.last_journal=None if undoing else result.journal;self.undo_button.setEnabled(self.last_journal is not None)
            self.review_journal=None;self.back.hide();self.apply_button.setText(tr('Rename files'))
            self.excluded.clear();self.overrides.clear()
            self.model.set_rows([bulk_rename.Entry(old,new,()) for old,new in result.pairs],set(),completed=True)
            self.model.editable=False
            self.summary.setText(tr('Restored names for {0} files.' if undoing else 'Renamed {0} files. File contents were not changed.').format(len(result.pairs)))
            self.refresh_history()
        self.lookup(fn,finish,lambda error:finish(error=error))

    def apply_names(self):
        if self.busy:return
        if self.review_journal:
            path,state=self.review_journal
            if state=='applied':self.run_rename(lambda:bulk_rename.undo(path,self.journal_dir,cancel=self.cancel,progress=lambda v:self.renameProgress.emit(round(v*100))),undoing=True)
            else:
                def recover():
                    items,_=bulk_rename.load_journal(path)
                    pairs=tuple((next((Path(item[key]) for key in ('temporary','source','target') if bulk_rename._matches(item[key],item['fingerprint'])),Path(item['temporary'])),Path(item['source'])) for item in items)
                    bulk_rename.recover(path)
                    return bulk_rename.RenameResult(path,pairs)
                self.run_rename(recover,undoing=True,recovering=True)
            return
        if self.plan is None or not self.apply_button.isEnabled():return
        plan=self.plan
        self.run_rename(lambda:bulk_rename.execute(plan,self.journal_dir,cancel=self.cancel,
            progress=lambda value:self.renameProgress.emit(round(value*100))))

    def undo_current(self):
        if self.last_journal is None or self.busy:return
        path=self.last_journal
        self.run_rename(lambda:bulk_rename.undo(path,self.journal_dir,cancel=self.cancel,
            progress=lambda value:self.renameProgress.emit(round(value*100))),undoing=True)

    def _cancel_all(self):
        self.preview_cancel.set();self.cancel.set()

    def cancel_or_close(self):
        if self.busy:self.cancel.set();self.summary.setText(tr('Cancelling and restoring original names…'))
        else:self.close()

    def closeEvent(self,event):
        self.preview_cancel.set()
        if self.busy:
            self.cancel.set();event.ignore();self.summary.setText(tr('Wait for the rename rollback to finish.'));return
        super().closeEvent(event)

    def save_rules(self):
        path,_=QFileDialog.getSaveFileName(self,tr('Save rename rules'),'rename-rules.json',tr('JSON (*.json)'))
        if path:Path(path).write_text(preset_json(self.rules),encoding='utf-8')

    def load_rules(self):
        path,_=QFileDialog.getOpenFileName(self,tr('Load rename rules'),'',tr('JSON (*.json)'))
        if not path:return
        try:
            if Path(path).stat().st_size>1_000_000:raise UserError('The preset is too large.')
            self.set_rules(read_preset(Path(path).read_text(encoding='utf-8-sig')))
        except (OSError,UserError) as error:self.error.setText(tr(str(error)))

    def import_csv(self):
        path,_=QFileDialog.getOpenFileName(self,tr('Import filename mapping'),'',tr('CSV (*.csv)'))
        if not path:return
        try:
            if Path(path).stat().st_size>20_000_000:raise UserError('The filename mapping is too large.')
            with Path(path).open(encoding='utf-8-sig',newline='') as source:
                sample=source.read(8192);source.seek(0)
                try:dialect=csv.Sniffer().sniff(sample,delimiters=',;\t')
                except csv.Error:dialect=csv.excel
                rows=list(csv.reader(source,dialect))
            names={}
            for item in self.paths:names.setdefault(item.name,[]).append(str(item))
            full={str(item):str(item) for item in self.paths}
            if len(rows)>100001:raise UserError('Use up to 100,000 files in one rename operation.')
            mapping={}
            for index,row in enumerate(rows):
                if not row:continue
                if len(row)!=2:raise UserError('CSV needs two columns: source and new_name.')
                old,new=[value[1:] if value.startswith('\t') else value for value in row]
                if index==0 and old.lower() in ('source','old','old_name'):continue
                matches=[full[old]] if old in full else names.get(old,[])
                if len(matches)!=1:raise UserError('A CSV source is missing or ambiguous: '+old)
                mapping[matches[0]]=new
            self.overrides.update(mapping);self.schedule_preview()
        except (OSError,UnicodeError,UserError,csv.Error) as error:self.error.setText(tr(str(error)))

    def export_csv(self):
        if self.plan is None:return
        path,_=QFileDialog.getSaveFileName(self,tr('Export filename mapping'),'rename-preview.csv',tr('CSV (*.csv)'))
        if not path:return
        def cell(text):return '\t'+text if text.startswith(('=','+','-','@')) else text
        try:
            with Path(path).open('w',encoding='utf-8-sig',newline='') as output:
                writer=csv.writer(output);writer.writerow(['source','new_name'])
                writer.writerows((cell(str(entry.source)),cell(entry.target.name)) for entry in self.plan.entries)
        except OSError as error:self.error.setText(str(error))

    def refresh_history(self):
        def work():
            files=sorted(self.journal_dir.glob('*.jsonl'),key=lambda path:path.stat().st_mtime_ns,reverse=True)[:20]
            result=[]
            for path in files:
                try:entries,state=bulk_rename.load_journal(path)
                except (OSError,UserError):continue
                result.append((path,len(entries),state))
            return result
        def loaded(items):
            self.history.blockSignals(True);self.history.clear();self.history.addItem(tr('Recent renames / recovery'),None)
            for path,count,state in items:
                if state in ('applied','prepared','staging','committing','needs_recovery'):
                    self.history.addItem(tr('{0} files · {1} · {2}').format(count,tr(state),path.stem[:8]),(path,state))
            self.history.blockSignals(False)
        self.lookup(work,loaded)

    def review_history(self,*_):
        selected=self.history.currentData()
        if selected is None:return
        path,state=selected
        self.preview_cancel.set();self.timer.stop();self.want_preview=False;self.revision+=1
        revision=self.revision
        self.apply_button.setEnabled(False);self.rules_pane.setEnabled(False);self.model.editable=False
        self.summary.setText(tr('Reading rename history…'))
        def read():
            items,_=bulk_rename.load_journal(path)
            rows=[]
            for item in items:
                current=Path(item['target']) if state=='applied' else next((Path(item[key]) for key in ('temporary','source','target') if bulk_rename._matches(item[key],item['fingerprint'])),Path(item['temporary']))
                rows.append(bulk_rename.Entry(current,Path(item['source']),tuple(item['fingerprint'])))
            return rows
        def loaded(rows=None,error=None):
            if revision!=self.revision or self.busy:return
            if error:
                self.error.setText(tr(error));self.leave_history();return
            self.review_journal=selected;self.model.set_rows(rows,set())
            self.back.show();self.apply_button.setText(tr('Undo these renames' if state=='applied' else 'Restore original names'))
            self.apply_button.setEnabled(True);self.summary.setText(tr('Review the original names below before applying recovery or undo.'))
        self.lookup(read,loaded,lambda error:loaded(error=error))

    def leave_history(self):
        self.review_journal=None;self.rules_pane.setEnabled(True);self.model.editable=True
        self.back.hide();self.apply_button.setText(tr('Rename files'));self.history.setCurrentIndex(0)
        self.schedule_preview()
