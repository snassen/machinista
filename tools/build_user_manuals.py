"""Build the English controller manuals from the current offline display renderers.

No hardware I/O. All application data lives in a disposable fixture directory.
"""
from pathlib import Path
import sys, os, tempfile, wave, array, math, hashlib, json, re
from xml.sax.saxutils import escape
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ['MACHINISTA_UI']='v2'
from PIL import Image
from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor, Color, white
from reportlab.lib.utils import ImageReader
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph, Table, TableStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from tests.test_fokus_v2 import fixture
from tools.audit.fokus_fein_cases import cases, apply
from app.controller_inputs import ControllerInputs
from app.mk2_surface import Mk2Surface
from app.mk3_surface import Mk3Surface
from app.mk3_display import Mk3Renderer
from app.mk3_state import snapshot as mk3_snapshot
from app.mk1_session import Mk1Surface
from app.mk2_display import Mk2Renderer,snapshot
from app.ni_display import frame
from app.waveform import read_envelope
from app.ui_inventory import WORKFLOWS

OUT=ROOT/'output/pdf'; ASSETS=ROOT/'tmp/pdfs/manual-assets'
OUT.mkdir(parents=True,exist_ok=True);ASSETS.mkdir(parents=True,exist_ok=True)
FONT='/System/Library/Fonts/Supplemental/'
for name,file in [('Manual','Arial.ttf'),('ManualBold','Arial Bold.ttf'),('ManualItalic','Arial Italic.ttf')]:
    pdfmetrics.registerFont(TTFont(name,FONT+file))
pdfmetrics.registerFontFamily('Manual',normal='Manual',bold='ManualBold',italic='ManualItalic',boldItalic='ManualBold')
W,H=595.276,841.89; M=44; CW=W-2*M
INK=HexColor('#29231e');ACCENT=HexColor('#b84b00');MUTED=HexColor('#6b5a4e');PALE=HexColor('#fff2e6');LINE=HexColor('#e4cdb9')
STYLE=ParagraphStyle('body',fontName='Manual',fontSize=11.2,leading=16.3,textColor=INK,spaceAfter=7)
SMALL=ParagraphStyle('small',parent=STYLE,fontSize=8.2,leading=11.2,textColor=MUTED)
HEAD=ParagraphStyle('head',parent=STYLE,fontName='ManualBold',fontSize=12,leading=16,textColor=ACCENT)

# Each entry is one deliberately paced workflow page. Controller-specific text
# is selected at build time, rather than pretending the two surfaces are equal.
CH=[]
def chapter(title,screens,intro,steps=(),notes=(),table=None):CH.append(dict(title=title,screens=screens,intro=intro,steps=steps,notes=notes,table=table))
def either(micro,mk2):return {'mikro':micro,'mk2':mk2}

chapter('Welcome to Machinista',['PAD'],
 'Machinista turns a Raspberry Pi into a standalone, controller-operated sampling groovebox. Build kits from your own WAV files, record audio, chop loops, play and edit patterns, arrange scenes, route audio and use compatible LV2 plug-ins.',
 notes=[('Your sounds and plug-ins','Build your library with your own WAV samples and compatible LV2 instruments and effects.'),
 ('How to use this guide','Start with Setup and Your first beat. Continue with the sampling and sequencing chapters as needed. The final screen atlas covers the registered workspaces, parameter pages and important variants. Its index lets you locate a display by its software workspace name.')])

chapter('Setup and first start',['STARTUP','AUDIO'],
 'Connect the controller by USB and connect headphones or speakers to a supported audio device. The prepared beta image starts the application without a desktop.',
 steps=['Write the supplied Pi 4 / Pi 5 image to an SD card of 8 GB or larger using a custom-image option. Do not override its prepared username or SSH settings in the imaging tool.',
 'Insert the card, connect the controller and audio device, then power the Pi. The controller shows the Machinista logo for about two seconds at connection; any input dismisses it. Allow about two minutes for first-boot expansion and a possible restart.',
 either('Open settings with SHIFT + MAIN. F1 selects AUDIO. Choose INTERFACE with the encoder and press ENTER.','Open settings with SHIFT + CONTROL. Display button 1 selects AUDIO. Turn encoder 1 to select INTERFACE and press ENTER.'),
 'Use AUTO for automatic USB-audio selection with the supported HAT as fallback. Alternatively select an available interface explicitly. Check SAMPLE RATE, BUFFER and MAIN OUTPUT before playing.'],
 notes=[('Beta hardware scope','The image contains Pi 4 and Pi 5 boot support. A new board, USB interface or HAT still needs its own boot and audio check; inclusion of firmware is not a completed hardware qualification.'),('Storage','Keep the boot SD card inserted while powered. Use USB media or the WebUI to transfer samples.')])

chapter('Know your controller',[],
 either('The Mikro MK1 has one 128 x 64 pixel screen, three display buttons and one push encoder. Context navigation makes additional functions available without requiring a computer.','The MK2 has two 256 x 64 pixel screens, eight display buttons and eight parameter encoders. The large master encoder and dedicated Group keys provide additional direct control.'),
 notes=[('Display controls',either('F1, F2 and F3 are above the display. Read their labels along the top edge. Turn the encoder to change the focused value; use the two arrows below the display to move between fields or pages as the current screen indicates.','Display buttons 1-4 belong to the left screen and 5-8 to the right. Encoders 1-4 are below the left screen and 5-8 below the right. A value above an encoder belongs to that encoder; blank fields have no parameter binding.')),
 ('Pad numbering','Pad 1 is at bottom left. Each row counts left to right: 1-4, then 5-8, 9-12 and 13-16 at the top. Pad function and lighting change with the active mode.'),
 ('Navigation controls',either('MAIN opens the persistent Volume/Swing/Tempo panel. SHIFT + MAIN opens settings. NAV selects contextual parameters. Hold VIEW, turn the encoder to select SONG, MIXER, EVENTS or LIVE FX, then release VIEW to open it.','CONTROL returns to the control view. SHIFT + CONTROL opens settings. The page arrows below SAMPLING switch parameter pages. NAVIGATE provides the functions assigned to VIEW on the Mikro.'))])

chapter('Reading the displays',['PARAM NAV','SAMPLER'],
 'The upper strip contains display-button actions. The body shows the current workspace and its content; the lower area holds parameter names, values or transport information. Highlighting identifies the active choice.',
 notes=[('Selection and focus','An inverted field or highlighted list row identifies the selection. In a waveform, the playback range remains clear while the area outside START and END is inverted. Sample/slice markers identify editable boundaries.'),
 ('Pages and fields',either('Page counts show how many parameter pages exist. NAV previews the destination before you release it. Arrow availability depends on context: a page arrow is useful only when a neighbouring page exists. Field positions describe parameter selection, not additional hidden workspaces.','Page counters refer to the current parameter bank. The physical page arrows switch banks; they do not automatically locate the transport. The two transport STEP arrows are separate controls.')),
 ('Temporary information','Status notices, such as a new audio connection or CHOKE ALL NOTES, clear after one second. They do not replace the underlying parameter values.')])

chapter('Navigation, hold and pin',['VIEW NAV','SAMPLING NAV'],
 'A held mode is a temporary workspace. Pinning keeps a supported mode open after the button is released. SHIFT shortcuts have their own meanings and should not be used as a general pin command.',
 steps=[either('Hold SCENE, PATTERN or PAD MODE to use that mode temporarily. While holding it, press MAIN to toggle its pin preference. Release the mode button. A pinned mode can be closed and reopened with its own button.','Hold a pad-related mode to work temporarily. Where PIN is shown, use its display button to toggle the pin state. Release the mode key. Use CONTROL to return to the control view.'),
 either('In the control view hold NAV. Use F2 for CHNL or F3 for PLUG-IN, turn the encoder to choose a destination, and check its name before releasing NAV. NAV + arrows select its page.','Press CONTROL for the control view. Use display buttons 1-3 for MASTER/GROUP/SOUND, then 5 for CHANNEL or 6 for PLUG-IN. Use the page arrows and the displayed module arrows to navigate.'),
 either('Within Sampling, hold NAV, choose RECORD, EDIT, SLICE or ZONE with the encoder, then release NAV. SHIFT + SAMPLING goes directly to Edit.','Within Sampling, display buttons 1-4 select RECORD, EDIT, SLICE and ZONE directly. SHIFT + SAMPLING goes directly to Edit.')],
 notes=[('View navigation',either('Hold VIEW and turn the encoder through the SONG, MIXER, EVENTS and LIVE FX icons. Release VIEW to open the selected workspace. Its icon stays selected when you return; press the encoder or F3 OFF to deselect, then release VIEW to return. F1 BACK clears every icon; release VIEW to return to the last Sound/control view. In the Events editor, VIEW + F2 GRID keeps zoom/scroll available. In Sample Edit or Slice with EDIT active, hold VIEW and turn the encoder to zoom directly; release VIEW to resume editing. SHIFT + VIEW still opens Mixer directly.','Hold NAVIGATE and choose IDEAS, SONG, MIXER, BROWSE or EVENTS with the labelled display button. The destination is highlighted before NAVIGATE is released.'))])

chapter('Projects, Groups, Sounds and Patterns',['GROUP','PATTERN'],
 'A project contains Groups, their Sounds, Patterns, Scenes and the Song. Understanding what owns a setting prevents edits from affecting the wrong part of a performance.',
 table=[('Object','What it contains / controls'),('Sound','One pad slot: sample zones or an LV2 instrument, voice settings, plug-ins, channel and MIDI routing.'),('Group','Sixteen Sound slots, its own Patterns, performance scale settings, mixer and effects.'),('Pattern','Events for one Group. Different Groups can play different Patterns at the same time.'),('Scene','A combination of Group Pattern references. An empty clip contributes no Pattern.'),('Song','An ordered sequence of Scene references. Reusing a Scene reuses its Patterns.'),('Master','The final project mix and master processing, rather than the selected Sound.')],
 notes=[('Select the right scope',either('In a control view, F1 selects MASTER, F2 GROUP and F3 SOUND. Hold GROUP and choose its pad to change Group.','In a control view, display buttons 1, 2 and 3 select MASTER, GROUP and SOUND. Dedicated A-H keys select Groups in the current bank.')),
 ('Selection is not erasure','Selecting a pad, changing a Pattern or switching a Group does not delete its content. A missing or muted Scene clip can make a populated Group silent.')])

chapter('Your first beat',['BROWSE','STEP'],
 'This short tutorial builds a drum kit, records a loop and saves it. Start with an empty project and three WAV files: a kick, snare and hi-hat.',
 steps=['Choose Group A and Sound 1. Press BROWSE. Open SD CARD, then Library/Kicks (or your own folder). Select a WAV and use LOAD or ENTER.',
 'Without leaving Browse, choose Sound 2 with its pad and load a snare. Choose Sound 3 and load a hi-hat. Enable PREHEAR when you want to audition the selected file.',
 either('Press MAIN, choose TEMPO with F3 and set a comfortable tempo. Return to the Sound view.','Press TEMPO and turn the large master encoder. Press TEMPO again to leave the panel.'),
 'Select an empty Pattern and set its length before recording. Enable the metronome if needed. Turn REC on and start PLAY, then play the pads.',
 'Let the Pattern loop. Turn REC off to hear the recorded notes without adding more. PLAY stops/starts the transport; RESTART returns to the beginning.',
 either('Open PROJECT from the shifted Scene actions or System settings. Choose SAVE. Use MANAGE to name a new project or make a separate copy.','Use SHIFT + ALL to save. Open PROJECT from System settings when you want to name a new project or use SAVE AS.')],
 notes=[('Check the result','You should hear the recorded kick, snare and hi-hat repeat at the displayed Pattern length. Playing with REC off must not create sequencer notes.')])

chapter('Browse folders and load samples',['BROWSE'],
 'Browse shows your folders and sample files. Sources contain folders and WAV files. Folders are listed before files; the list is sorted by name.',
 steps=[either('Press BROWSE. Turn the encoder to move up or down the list. Press ENTER or the OPEN/LOAD softkey. F1 BACK goes to the parent folder; at the source root it returns to the source list.','Press BROWSE. Use the displayed selection encoder to move through the list. ENTER or display button 8 LOAD opens the selection. Display button 1 BACK goes up.'),
 'Choose SD CARD or an attached USB source. Open folders until the desired WAV appears. A folder prefix distinguishes a folder from a sample.',
 either('Use F3 PREH to toggle prehear. Auditioning does not load the file into the Sound.','Use display button 4 PREHEAR to toggle auditioning. Auditioning does not load the file into the Sound.'),
 'Choose the destination pad while Browse stays open, then load the selected sample. Repeat for other pads without returning to the main Sound view.'],
 notes=[('USB media and projects','A USB source appears when mounted and disappears when removed. Use COLLECT SAMPLES before moving a project between systems. Do not assume that every externally browsed file is already in a portable project folder.'),
 ('Supported content','The controller file browser lists WAV files. Use the plug-in browser to load compatible LV2 instruments and effects.')])

chapter('Play, locate and set tempo',['PAD','TEMPO'],
 'Transport control is independent of the current Sound or sample-edit page. The tempo panel is persistent until you leave it; it is not a short notification.',
 table=[('Control','Action'),('PLAY','Toggle transport playback. REC is a separate recording state.'),('RESTART','Return to the beginning, including while playback continues.'),('Transport STEP left / right','Locate by Arrange Grid. Hold for repeated movement every 0.25 seconds.'),('SHIFT + transport STEP','Locate with the finer Step Grid.'),('SHIFT + PLAY','Toggle the metronome.'),('SHIFT + REC','Start recording with a count-in.'),('SHIFT + MUTE','Choke all voices, previews and held generators from any workspace.')],
 notes=[('Tempo',either('MAIN opens the Volume/Swing/Tempo panel; F3 selects TEMPO. Turn the encoder for normal changes and hold SHIFT for fine changes to two decimal places. SHIFT + ENTER is tap tempo.','TEMPO selects the master tempo panel. Turn the large master encoder; hold SHIFT for fine changes. Tap tempo uses SHIFT + ENTER in this beta. VOLUME and SWING select their persistent panels.')),
 ('Separate arrows',either('The arrows beneath the display navigate parameters. The two lower transport arrows locate playback.','The arrows beneath SAMPLING switch pages. The lower transport arrows locate playback. Do not confuse them with the master-section arrows.'))])

chapter('Record and overdub a Pattern',['RECORD SETTINGS','PATTERN'],
 'Pattern recording stores pad/MIDI note events. Audio sampling records an input waveform; these are separate operations. The REC state controls whether live playing is written into the sequencer.',
 steps=['Select the Group and Pattern you want to edit. In PATTERN, turn the Mikro encoder or MK2 encoder 1 to set LENGTH; SHIFT gives single-step changes. Check that the Scene has an active clip for that Group.',
 'Press GRID for grid/quantize options; SHIFT + GRID opens RECORD SETTINGS. Set recording quantize and count-in there. Holding REC for one second also opens length/grid preparation; releasing it returns to recording.',
 'Enable REC, start PLAY and perform. The displayed Pattern length defines the loop. On later passes, overdub adds events unless a different recording mode is selected.',
 'Turn REC off to audition. If a part is wrong, erase or undo it rather than clearing the Sound slot. Save after you are satisfied.'],
 notes=[('Quantize and timing','Quantize changes note positions against the selected grid. Quantize 50% moves notes partway toward the grid. Swing and nudge are separate timing tools; they can intentionally move playback away from the straight grid.'),
 ('No unexpected note capture','If notes seem to appear while auditioning, check REC first. A lit recording state can remain enabled when you change views. Check the Events editor rather than assuming the pad sample itself has changed.'),
 ('Pattern length','Long Patterns have additional step banks and editor pages. FOLLOW moves the visible window with playback; turning it off only changes the view, not the loop length.')])

chapter('Program the Step sequencer',['STEP'],
 'The sixteen pads become step switches for the selected Sound. Lit steps contain notes; the playhead identifies the running position. Additional banks cover longer Patterns.',
 steps=[either('Use the STEP MODE shortcut, SHIFT + NOTE REPEAT, to open Step mode. Select the Sound or keyboard note you want to program first.','Press STEP. Select the Sound or keyboard note you want to program first.'),
 'Press pads to set or clear steps in the visible bank. For a sliced or pitched Sound, the last played keyboard note is used when available, rather than always using the first slice.',
 'Change the step bank with the navigation controls. Enable FOLLOW to bring the active playback bank into view automatically.',
 'Use FIX VEL when you want consistent inserted velocities. DOUBLE expands the Pattern with duplicated content.'],
 notes=[('View versus content','FOLLOW does not add notes and does not change the Pattern length. If the playhead is absent, check whether this Pattern is the active clip and whether playback is running.'),
 ('Fine event edits','Use the Events/grid editor to change an individual note, probability or length. Step pads are best for fast on/off programming rather than detailed multi-note editing.')])

chapter('Select and edit individual events',['PATTERN GRID','GRID EDIT'],
 'The Events editor displays Sound rows or MIDI pitches against time. It is the detailed editor for moving, selecting and changing individual notes.',
 steps=[either('Open PATTERN and press ENTER, or use SHIFT + SELECT. F1 switches between Sound rows and pitches.','Open PATTERN and use EDITOR, or use SHIFT + SELECT. The SELECT/EVENTS display actions switch the editor presentation.'),
 either('Turn the encoder to move the time cursor. Hold SHIFT and turn to change the Sound row or pitch. F2 toggles the notes at the cursor into the selection. SHIFT + F2 toggles all relevant notes.','Use the labelled time/row controls and the SELECT actions. ALL and NONE set or clear the event selection; UP/DOWN move the visible row focus.'),
 either('Press F3, ENTER or the encoder to open the event edit view. Arrows choose POSITION, NOTE, VELOCITY, PROBABILITY or LENGTH. Turn the encoder to change the value.','Open EVENTS/edit for the focused selection. Turn the encoder underneath POSITION, NOTE, VELOCITY, PROBABILITY or LENGTH to change it.'),
 'Return to the grid with the done/back action. Use ERASE and confirm when deleting selected events. Cursor navigation pauses Follow so you can work without the view moving away.'],
 notes=[('Selection scope','A selected set takes priority over the cursor target. In pitch view, the Sound remains the same while the note changes. When several notes share a cell, SHIFT + navigation arrows cycle the focused voice on the Mikro.'),
 ('Zoom and follow',either('View navigation changes the visible time span and scroll position. It is not the note-selection editor. Re-enable FOLLOW when you want the display to track playback again. On the Mikro, hold SHIFT and press F1, or hold VIEW, press F2 GRID and then F3 FOLLOW.','View navigation changes the visible time span and scroll position. It is not the note-selection editor. Re-enable FOLLOW when you want the display to track playback again. Press the FOLLOW display button (button 3); its highlight and LED show whether Follow is enabled.'))])

chapter('Keyboard, scales and 16 velocities',['PAD CONFIG'],
 'Normal pad mode plays sixteen different Sounds. Keyboard mode plays pitches of one focused Sound. A sliced Sound uses mapped note zones, so different keyboard pads can address different slices.',
 steps=['Use SHIFT + PAD MODE to enter Keyboard mode. Choose ROOT and SCALE, then play. The underlying Sound remains selected while the pads generate different MIDI notes.',
 'Choose a chord mode if needed. HARM builds chords from the selected scale or chromatic intervals; SET uses Machinista chord voicings.',
 'Use FIX VEL for a constant performance velocity. The 16 VEL mode instead spreads sixteen velocities of the focused Sound across the pads.',
 'Return to PAD mode when you need sixteen different drum Sounds rather than pitches of one Sound.'],
 notes=[('Lighting','Held keyboard notes light while played. Root/C notes are distinguished in keyboard layouts. Mapped slices and the selected/last-played slice are indicated, so an unmapped pad is not mistaken for a loaded slice.'),
 ('Choke and link','Pad configuration also contains choke and link groups/modes. Use a shared choke group for mutually exclusive hits, such as open and closed hats. Link groups can trigger related Sounds together.'),
 ('Transpose shortcut','SHIFT + pads 13/14 and 15/16 transpose sequencer events by semitone and octave. They are not a universal keyboard-octave shortcut.')])

chapter('Note Repeat and arpeggiation',['NOTE REPEAT','ARP'],
 'Note Repeat generates repeated drum hits while pads are held. The arpeggiator generates notes from held pitches or chords. With playback running, repetitions follow the transport grid.',
 steps=['Hold NOTE REPEAT and play pads. Select the rate before or during the performance. Use LOCK if you want repeat to remain available after releasing the mode key.',
 either('F1/F2 select the displayed repeat presets. SHIFT + F3 changes preset bank. Select RATE or DIVISION with the arrows and turn the encoder when you need a different value.','Display buttons 5-8 select 1/8, 1/16, 1/32 or 1/64. The DIVISION action cycles NORMAL, TRIPLET and DOTTED. LOCK and HOLD have their own labelled actions.'),
 'For melodic repetition, use Keyboard mode and the arpeggiator parameters. Choose direction, octave range, gate, dynamic and sequence as required.',
 'Turn REC on when you want the generated performance written into the Pattern. SHIFT + MUTE releases all held/repeating notes.'],
 notes=[('Grid alignment','During playback, a pad hit between subdivisions waits for the next repeat boundary. It does not restart the repeat clock. When transport is stopped, repeat uses its own running interval.'),
 ('Hold versus lock','LOCK keeps the repeat mode active. HOLD retains the played arpeggiator notes. These controls solve different problems; disable HOLD if notes continue after your fingers are lifted.')])

chapter('Sampling: choose an input and record',['SAMPLING'],
 'Sampling records a waveform into the selected Sound. Choose the target pad while the Record page remains open. The stereo meters show the incoming level and the Detect threshold marker.',
 steps=['Press SAMPLING and choose RECORD. Select EXT MONO, EXT STEREO or INTERNAL. Choose an available input channel/pair, or the internal source you want to resample.',
 'Play the source and inspect the meters. Adjust the source gain and, on supported HAT hardware, Input Gain. Leave headroom; a clipped recording cannot be repaired by normalizing it.',
 'Select DETECT to arm a threshold-triggered recording, or SYNC for transport/grid-related capture. Set threshold or length/synchronization options before arming.',
 'Use the displayed START/REC action. In DETECT, recording waits for the signal to cross the threshold; the manual trigger action can start it while armed. STOP finishes the take and CANCEL abandons it.',
 'Play the target pad to check the recording. Recorded files use simple numbered Sample names. Use the available history actions to return to an earlier take.'],
 notes=[('Input rate','Use a sample rate supported by the connected interface. A rate mismatch can sound like a bitcrusher. Recheck AUDIO > SAMPLE RATE when changing devices.'),
 ('Audio capture versus notes','The Record page captures audio. The transport REC button controls sequencer event recording. Monitor the correct state before recording a new take.')])

chapter('Trim, select and process a sample',['SAMPLE EDIT','STRETCH'],
 'Sample Edit separates the playback range from the processing selection. START and END trim what is played. A selection identifies the portion affected by a processing command.',
 steps=['Use SHIFT + SAMPLING for direct access to Edit. Select the correct Sound and sample before changing a boundary.',
 either('Use the arrows to focus START or END and turn the encoder. Hold NAV to select the playback-range or selection page; check the destination preview before releasing.','Use encoders 1 and 2 for START and END. The page arrows switch playback-range and selection banks. Encoders 3 and 4 remain ZOOM and SCROLL.'),
 'Choose a processing action with the labelled previous/next actions. NORMALIZE raises the sample level; other operations act on the selected audio according to their settings. Confirm APPLY only after checking the range.',
 'For STRETCH, set its tempo/length options and audition before APPLY. CANCEL returns without committing the preview.'],
 notes=[('Normalize and slices','Normalize the source sample when you want all slices to inherit the change. A slice is a range of that source, not a separate normalization target. Zone gain is a different playback parameter.'),
 ('Original audio','Processing creates derived audio rather than silently overwriting the source file. SAVE AS and COLLECT SAMPLES are still recommended before restructuring an important project.'),
 ('Deleting','Clearing a Sound slot removes the Sound assignment. It is different from deleting a recording/file. Use the explicit sample-delete view and confirmation for file deletion.')])

chapter('Zoom and scroll the waveform',['SAMPLE EDIT','CHOP'],
 'Zoom changes the amount of audio visible, not the playback speed or sample length. Scroll moves the visible window. The edited range and its markers remain part of the waveform.',
 steps=[either('In Sample Edit, or Slice with EDIT active, hold VIEW and turn the encoder to zoom directly. Release VIEW to return to trim/slice editing. While holding VIEW, the right arrow selects SCROLL and the left returns to ZOOM. Without Slice EDIT, VIEW + F2 WAVE still opens waveform controls.','In Edit, Slice or Zone, turn encoder 3 for ZOOM and encoder 4 for SCROLL. These controls are on the same page as the waveform.'),
 either('The wave controls can also use pads: pad 2 zooms out, pad 6 zooms in; pads 1 and 3 scroll left/right. Pin VIEW with MAIN while VIEW is held if you prefer to release the key.','Zoom toward the cut you want to inspect, then scroll as needed. Changing zoom anchors to the relevant range boundary when it is visible.'),
 'Return to the boundary control to move START or END. Fine changes become easier to judge after zooming in.',
 'In Slice Edit, replay the slice to refocus its boundary without losing the zoom level you selected.'],
 notes=[('Slice focus','At overview zoom the selected slice is centred with neighbouring audio. At close zoom the selected START or END cut is centred instead. Use left/right page navigation in Slice Edit to choose START or END; replay retains that choice.'),
 ('Viewport persistence','Replaying a slice preserves zoom. Selecting a different sample asset can reset its viewport. Zoom is a view operation and does not modify slice positions.')])

chapter('Slice automatically or on a grid',['CHOP'],
 'Slice mode places cut points in a source sample. You can audition and refine those cuts before assigning slices to Sounds or keyboard zones.',
 table=[('Mode','Use it for / principal setting'),('SPLIT','An equal number of sections. Choose the division/count.'),('GRID','Musical divisions based on the source tempo and selected grid.'),('DETECT','Transient-driven cuts. Adjust sensitivity and inspect the resulting boundaries.'),('MANUAL','Place cuts during playback with the pads; see the next chapter.')],
 steps=['Open SAMPLING > SLICE. Choose the required MODE and set its parameters. The waveform and slice count update for that choice.',
 'Set BPM to AUTO when the inferred tempo is useful, or MANUAL when you know the source tempo. Use ADJUST half/double for a tempo that is interpreted at the wrong musical multiple.',
 'Audition the slices with the pads. Enter EDIT to refine a cut before applying it. Use APPL.TO when you want to choose another Group or a specific Sound target.'],
 notes=[('A reversible plan','Cuts are range metadata while you work. APPLY turns the plan into playable assignments. Changing an automatic split configuration can regenerate the cut plan, so save important work before trying a different slicing strategy.'),
 ('Tempo is source information','The slice BPM describes the source loop and generated Pattern interpretation. It does not mean the source recording was made at the project tempo.')])

chapter('Manual live chopping and Slice Edit',['CHOP'],
 'Manual chopping lets you place cuts while listening. Slice Edit then lets you correct those boundaries without rebuilding the entire cut plan.',
 steps=['Choose MANUAL with EDIT off. Press pad 1 to start the source sample. Strike the next unused pad when you hear the next desired cut. Continue with successive pads.',
 'Press an existing slice pad to replay from that start point. After the sample has finished, an existing slice pad can restart playback; you do not need to recreate the slices.',
 'Enter EDIT and play the slice you want to adjust. START is the initial boundary focus. Choose START or END with left/right navigation, then adjust the corresponding boundary.',
 'Zoom and scroll to inspect the cut. Replaying a pad preserves zoom and the START/END focus. Use SPLIT/ADD for another boundary or REMOVE for the selected cut; DEL ALL clears the complete cut plan.'],
 notes=[('Protect the current work','Auditioning an existing pad does not add a new slice. The next unused pad creates a cut only during live chopping. Keep EDIT enabled while refining existing cuts, and avoid regenerating an automatic mode accidentally.'),
 ('Context around the cut','The selected waveform appears centrally with neighbouring slices at overview zoom. Once the sample no longer fits, the chosen cut is brought into view so you can hear and see the same boundary.')])

chapter('Apply slices to a Sound or Group',['SLICE TARGET','ZONE'],
 'APPL.TO chooses the destination before APPLY. You can map a set of slices inside one Sound or distribute slices to a Group. Single-slice export assigns the selected range to a Sound slot.',
 steps=['Audition and select the desired slice, then open APPL.TO. Choose the target Group and first Sound/all-Sounds target shown by the interface.',
 either('Use the target fields and encoder. GROUP plus a pad can choose the Group; bank actions expose further Group banks. Confirm the displayed destination before applying.','Use the GROUP and SOUND encoders on the target page, or a dedicated Group key. BANK-/BANK+ expose further banks. Confirm the displayed Group and Sound.'),
 'For one slice, choose the single-slice option (SINGLE / EDIT action on the Apply To page), choose its Sound slot, then APPLY. This is an assignment workflow, not a requirement to export a WAV first.',
 'For a full slice set, choose the desired target and Pattern-creation option, then APPLY. For keyboard mapping, return to Keyboard mode and play only the mapped slice notes.'],
 notes=[('MONO means voice behaviour','MONO on Group apply sets Polyphony = 1 and Choke Group = 1 for the assigned Sounds. It does not convert a stereo WAV to a mono file.'),
 ('Destination content','Applying to occupied Sounds can replace their assignments. Use another Group or save a project copy when you need to keep the existing kit.'),
 ('Further edits','ZONE exposes the applied key/velocity mapping and per-zone playback parameters. Return to SLICE > EDIT to work on the slice plan rather than accidentally editing a different Sound.')])

chapter('Zones and layered sample mapping',['ZONE'],
 'A zone associates a sample range with key and velocity ranges. Use zones for sliced keyboard maps, multisamples and velocity layers. Several zones can belong to one Sound.',
 table=[('Zone page','Parameters'),('PLAY','START and END of the zone.'),('LOOP','Loop on/off, loop start/end and crossfade.'),('TUNE','Tune, gain, pan and root note.'),('ENVELOPE','Zone attack and decay.'),('MAP','Lowest/highest key and lowest/highest velocity.')],
 steps=['Open SAMPLING > ZONE and select the zone you want to inspect. PREV/NEXT moves between zones; ADD creates an additional mapping and REMOVE removes the selected mapping.',
 either('Hold NAV and use the page arrows to choose the zone parameter page. Use the normal arrows for fields, then turn the encoder.','Use page arrows for parameter banks. Encoders 1/2 edit the shown zone fields; 3/4 remain ZOOM/SCROLL.'),
 'Play notes across the key and velocity ranges and check that the intended sample triggers. Check root note when an applied slice or multisample sounds pitched incorrectly.'],
 notes=[('Gain versus normalization','Zone gain is a playback multiplier. It does not rewrite or normalize the source file. Source normalization should be performed in Sample Edit before evaluating a complete sliced Sound.'),
 ('Overlapping mappings','Overlapping key and velocity ranges can layer audio. If a Sound seems unexpectedly loud, inspect overlapping zones rather than compensating only at the Master.')])

chapter('The Sampler: voice, envelopes and filters',['SAMPLER'],
 'Sampler parameters belong to a Sound. Use them while playing the pads to hear the result. An LV2 instrument in the first instrument slot replaces the built-in sample source for that Sound.',
 table=[('Page','Purpose'),('VOICE','Polyphony, legato glide and pitch-bend range.'),('PITCH/ENV','Tune, reverse and ONESHOT/AHD/ADSR volume envelope.'),('FX/FILTER','Compression, drive, sample-rate/bit reduction and OFF/LP2/BP2/HP2/EQ filter.'),('MOD ENV','Attack/decay modulation of pitch, cutoff and pan.'),('LFO','Shape, free/synced speed, phase and pitch/filter/pan depth.'),('VEL/MOD','Velocity and modulation-wheel influence, including start and cutoff.')],
 steps=[either('Select SOUND with F3. Hold NAV, choose PLUG-IN with F3, select SAMPLER and release NAV. Hold NAV with arrows to change its page; arrows alone select fields.','Select SOUND with display button 3, PLUG-IN with button 6 and the Sampler slot. Use page arrows for parameter banks and encoders under the displayed fields.'),
 'For a shaped sustained Sound choose ADSR. For a drum hit use ONESHOT or AHD. Parameters not used by the chosen envelope type are hidden.',
 'Choose LP2, BP2, HP2 or EQ, then adjust cutoff and resonance or EQ gain/width. Cutoff uses equal travel per octave; hold SHIFT for four-times-finer changes. Play the pad to compare the result.'],
 notes=[('Two different kinds of effect','The Sampler filter is built in at Sound level. An LV2 filter is a separate chain plug-in and may also process a Group or Master. Deliberate SR/BITS reduction produces a bitcrusher effect; it is not a recording-rate setting.')])

chapter('LV2 plug-ins: add, replace and remove',['PLUGIN BROWSE','PLUGIN'],
 'Each Sound, Group and Master has its own plug-in chain. Compatible LV2 effects can process audio; an instrument belongs at the first instrument position of a Sound chain.',
 steps=['Choose the intended MASTER, GROUP or SOUND scope. Open PLUG-IN navigation and select an existing slot or ADD PLUGIN.',
 'Use SHIFT + BROWSE to open the plug-in browser even when a slot is already occupied. Select an effect/instrument from the compatible catalog and load it into the chosen position.',
 'Turn the shown controls and play the pads to audition. Page through additional parameters. BYPASS lets you compare processed and unprocessed audio.',
 either('Select the slot with NAV + arrows. In plug-in navigation/slot editing use REMOVE, or SHIFT + BROWSE and select the remove entry. Confirm REMOVE PLUGIN?.','Hold SHIFT in the plug-in view for chain actions. Display button 6 opens BROWSE and 7 is REMOVE; confirm the removal. COPY/PASTE/MOVE are shown on the left.')],
 notes=[('Chain management','COPY/PASTE duplicate the selected plug-in state; MOVE reorders it. An instrument must remain first. Removing/reordering also updates associated parameter references, so save a copy before restructuring a complex automated chain.'),
 ('Real-time budget','Plug-ins differ widely in processing cost and reported latency. Test each chain at the desired buffer. A tape or look-ahead effect can add audible delay even when pads and displays respond immediately.')])

chapter('Channel routing and the Mixer',['CHANNEL','MIXER'],
 'Channel properties describe where a Sound or Group receives and sends audio. The Mixer presents levels, pan and routes together. Direct hardware destinations depend on the selected interface.',
 steps=['Choose SOUND, GROUP or MASTER. Open CHANNEL and select OUTPUT. Use AUDIO for the main destination, AUX1/AUX2 for sends and, at Sound scope, MIDI for external-note output.',
 'To use separate interface outputs, select the output port/pair offered by the interface. Route the selected Sound or Group and verify the destination on the interface itself.',
 either('Open Mixer with SHIFT + VIEW. F1/F2/F3 choose Master/Group/Sound. Navigate to the desired channel and choose its level, pan or output field.','Hold NAVIGATE and choose MIXER. Display buttons 1-3 choose scope; 5-7 choose LEVEL, PAN or ROUTE. The vertical strips align with the parameter encoders.'),
 'Set Main Output and a separate Cue Output in Audio settings. Use Cue Level for audition level. Main and Cue may not overlap the same hardware channels.'],
 notes=[('Input and feedback','INPUT selects external/internal channel sources and monitoring-related properties. Avoid routing a destination back into its own input; invalid routing cycles are rejected.'),
 ('Musical level versus interface level','Master level adjusts the project mix. The ULTRA HAT headphone/speaker controls change codec output level and Input Gain changes capture gain. Hardware-specific controls are not universal USB-interface gain knobs.')])

chapter('Mute, solo, selection and duplication',['MUTE','SELECT'],
 'Focus chooses what you edit. Multi-selection chooses a set of targets. Mute/solo changes what can be heard. These states are independent and remain visible through their mode views and LEDs.',
 steps=['Hold MUTE or SOLO and press the relevant Sound pad to toggle its state. Group-level actions affect the selected Group; on MK2 the dedicated Group keys operate Group mute/solo in those views.',
 'Muting silences the running sample immediately rather than waiting for the tail to finish. If an entire Group is silent, inspect Group mute and Scene clip activation as well as Sound mute.',
 'Use SELECT for quiet focus and multi-selection. Choose ALL/NONE where available. On MK2, ALL toggles between all sixteen Sounds and the focused Sound; in the event grid it toggles event selection.',
 'Use DUPLICATE with the appropriate source and destination selection. Check whether you are duplicating a Sound, a Pattern or a Scene before confirming the operation.'],
 notes=[('Global stop for voices','SHIFT + MUTE chokes all active sample voices, plug-in/MIDI notes, previews and held repeat/arp notes from any screen. It does not switch your edit workspace.'),
 ('Clear is not Sound reset','SHIFT + CLEAR removes targeted Pattern notes. To empty a Sound slot, hold SHIFT + ERASE and press its pad. This clears its sample/plug-in assignment; it is a different operation from muting it.')])

chapter('Scenes and Song arrangement',['SCENE','SONG'],
 'A Scene recalls one Pattern reference per Group. Song is an ordered list of Scenes. Repeating a Scene repeats those references; editing a shared Pattern changes every place that uses it.',
 steps=['Create Patterns in the relevant Groups. Select a Scene, then choose each Group Pattern that belongs in that Scene. Leave a clip empty when the Group should not play.',
 'Select another Scene and build a variation. During playback the Perform Grid determines when a requested Scene change takes effect.',
 either('Open SCENE, hold SHIFT and use the SONG action. PROJECT is the neighbouring utility action.','Hold NAVIGATE and use SONG. Release NAVIGATE after the Song destination is highlighted.'),
 'Select a Scene before opening Song. INSERT (F1 / display button 1) inserts that Scene at the selected Song position. Turn the selection encoder to move through entries. PLAY (F2 / button 2) toggles Song playback; DELETE (F3 / button 3) removes an entry after confirmation.'],
 notes=[('Scene length','An automatic Scene length follows its active Patterns; an explicit Scene length can override it. Patterns can have different lengths and loop within a longer Scene.'),
 ('Make a variation independent','Duplicating a Scene does not necessarily make its Patterns independent. Use the unique/copy workflow when the variation must have its own editable Patterns.'),
 ('Master automation','Pattern automation lives with the Group Pattern. Song master automation is handled separately from those per-Pattern lanes.')])

chapter('Automation, macros and MIDI Learn',['MACRO','MACRO ASSIGN'],
 'Automation stores parameter movement against musical time. Macros expose useful controls together. MIDI Learn maps an external controller to the parameter you have touched.',
 steps=[either('Play the Pattern and use the AUTO-writing gesture shown by the current parameter view. On Mikro, hold SHIFT while changing supported parameters to write their movement.','Play the Pattern, hold AUTO WR. and turn a parameter encoder to write movement. SHIFT + AUTO WR. toggles a locked write state; press AUTO WR. again to leave it.'),
 'Release write mode and listen to the next loop. Parameter playback is transient: the saved base value remains distinct from the automated value.',
 'Use Macro Assign to select a target parameter, then expose it in the Macro page. Check the Sound/Group/Master scope before assigning.',
 'For MIDI Learn, touch the target parameter, open MIDI LEARN and send the external control message. Test the mapping with automation writing off first.'],
 notes=[('Clear the intended lane','SHIFT + pad 10 (CLR AUTO) clears automation according to the current target/selection. It does not delete the sample or the Pattern notes. Save before clearing automation you may need again.'),
 ('Scope and persistence','Sampler, routing, value and compatible plug-in parameters have automation targets. MIDI mappings and plug-in references are stored with the project; moving/removing a plug-in changes the corresponding targets.')])

chapter('MIDI ports, clock and Bluetooth',['MIDI IN','BLUETOOTH MIDI'],
 'Use Settings > MIDI for input, output, channel, clock, offset and learning. Available USB MIDI and controller DIN endpoints appear when their devices are connected.',
 steps=['Select MIDI INPUT for incoming notes and controllers, then MIDI OUTPUT for the external destination. Set the Sound output channel for the receiving instrument.',
 'Set CLOCK to OFF, IN or OUT. IN follows an external clock; OUT sends clock. Use CLOCK OFFSET to compensate the receiving setup after testing against a metronome.',
 'Open BLUETOOTH MIDI. Enable it with ON/OFF. On Mikro, F2 scans, SHIFT + F2 opens pairing and ENTER toggles connection for the selected device. On MK2, use PAIR, SCAN, CONNECT and DISCONN on their labelled display buttons.',
 'For an iPad, use a Bluetooth-MIDI-capable app to connect. For a keyboard, put the keyboard in its Bluetooth-MIDI pairing mode, then scan/connect from Machinista.'],
 notes=[('Bluetooth MIDI is not Bluetooth audio','This connection carries note/control/clock messages where supported. It is not an audio link to the iPad and does not make the Pi USB-C power connector a universal audio/MIDI peripheral port.'),
 ('Availability','A device can be visible in the port list without a complete end-to-end cable/app test. If no notes arrive, check selected port, channel, pairing and the receiving app rather than only the device name.')])

chapter('Project names, presets and portable saves',['PROJECT','PROJECT NAME'],
 'PROJECT provides SAVE, LOAD and MANAGE. Manage creates named projects, renames/deletes saved slots, collects samples and saves/loads Sound or Group presets.',
 steps=['Open PROJECT from System settings or the shifted Scene actions. Choose MANAGE, then NEW PROJECT. The new name starts empty.',
 'Turn the name encoder to choose a character and use navigation arrows to move the cursor. RANDOM suggests a name. SHIFT changes CANCEL to CLEAR; OK commits a valid name.',
 'Use RENAME to change a display name or SAVE AS to create an independent saved slot. DELETE asks for confirmation. Deleting a saved slot leaves the current working copy available as UNTITLED.',
 'Use SAVE SOUND/SAVE GROUP for reusable presets. Use COLLECT SAMPLES to copy referenced sample assets into a portable project location before moving it.'],
 notes=[('Backup is more than one project JSON','Keep the project together with its collected audio and any plug-in state. Preserve the original project before replacing samples or changing a chain.'),
 ('Save shortcut',either('Use PROJECT > SAVE. The Project workspace is also available through System settings.','SHIFT + ALL saves the current project. Plain ALL is selection, not save.')),
 ('RAM and storage','Samples are loaded into RAM for playback; this is not a disk-streaming sampler. SAMPLE RAM can inspect usage and free unused sample memory while stopped.')])

chapter('Relink missing files and export',['MISSING SAMPLES','EXPORT'],
 'A project can reference unavailable external audio. Relink finds replacements. Export produces audio or MIDI files for use outside the groovebox without recording the physical outputs in real time.',
 steps=['If a project reports missing samples, open MANAGE > RELINK SAMPLES. Review the missing entry and search results, or browse to the exact replacement. Do not choose a similarly named but unrelated sample.',
 'For audio export choose MANAGE > EXPORT AUDIO. Set RANGE to PATTERN, SCENE or SONG and SOURCE to MIX, SOUND, GROUP or a stem set.',
 'Set sample rate, format/depth, tail length, normalization, loop optimization and destination. Confirm enough free space on SD/USB, then start the render.',
 'For notes choose EXPORT MIDI. After export, inspect the completion screen for the destination and file. Test the file in the receiving application.'],
 notes=[('Range matters','PATTERN export uses the selected Group Pattern. SCENE includes its active clips; SONG follows the Song list. A Song export requires a nonempty arrangement.'),
 ('Tails and loops','A tail preserves effect decay after the musical end. Loop optimization and long tails serve different goals. Choose settings according to whether the result is a repeating loop or a finished track.'),
 ('Export boundaries','The offline renderer uses the project engine and compatible plug-ins. External hardware audio is not recreated by exporting MIDI notes or an internal audio mix.')])

chapter('Audio and controller settings',['SETTINGS','SYSTEM'],
 'SHIFT + MAIN on Mikro or SHIFT + CONTROL on MK2 opens three folders: AUDIO, MIDI and SYSTEM. Choose a folder with its display button, select an entry and open it with ENTER.',
 table=[('Folder / item','Use'),('AUDIO / INTERFACE','AUTO or a detected class-compliant interface.'),('SAMPLE RATE / BUFFER','Device rate and latency/CPU tradeoff. Start stable, then lower the buffer.'),('MAIN / CUE','Choose non-overlapping outputs and audition level.'),('PLUGIN DELAY','Optional latency compensation; default off for low latency. Change while stopped.'),('HEADPHONE / SPEAKER / INPUT','Codec level controls for supported ULTRA HAT hardware.'),('SYSTEM / display','Brightness and contrast per controller; MK2 has separate left/right contrast.'),('SYSTEM / pads','Sensitivity and velocity curve per controller.'),('SYSTEM INFO','Logo/version first; CPU across all cores, RAM and paged storage bars.')],
 notes=[('Adjust only the connected surface','Controller display and pad settings are scoped to the device from which they are changed. System Info opens on the logo/version page: Mikro then has CPU/RAM and storage pages; MK2 shows CPU/RAM on the right and storage on following pages.'),
 ('CPU figures','The CPU percentage is overall use across cores, not a single core reading. Plug-ins, voices, sample rate and buffer size all affect the available headroom. A low idle value does not guarantee a heavy set will run without overruns.')])

chapter('WebUI, Wi-Fi and sample transfer',[],
 'The WebUI manages library files and shows system information. It also connects the Pi to a router. You can use it from a browser on a computer, tablet or phone.',
 steps=['When no saved router is connected, join Machinista-XXXX. XXXX is the last four hexadecimal characters of the permanent Wi-Fi MAC address. The hotspot password is machinista.',
 'Open http://10.42.0.1:8080. Upload your WAV files into Library/Kicks, Library/Snares, Library/Hi-Hats, Library/Loops or your own folder. Browse those folders from the controller.',
 'Under WLAN, scan/select your router and enter its password. The Pi switches networks. Rejoin that home network and open http://machinista.local:8080, or its assigned IP address.',
 'If the router connection fails or disappears, the hotspot returns. A router does not need Internet access for local use. The single internal Wi-Fi radio changes between router and hotspot operation.',
 'For SMB use smb://machinista.local/Samples; on Windows use \\\\machinista.local\\Samples. Username and password are both machinista. The share exposes the SD sample library.'],
 notes=[('Preview and access','WebUI prehear plays on your browser device, not on the Pi audio outputs. This beta intentionally has no WebUI login; anyone on the connected network can access its exposed file functions.'),
 ('Transfer limits','WAV uploads are limited to 1 GiB per file with a free-space reserve. Uploads do not silently overwrite an existing local file. Attached USB sources are available through the WebUI.'),
 ('Boot image accounts','The distributable image uses the machinista account and excludes the source device\'s personal projects and Wi-Fi credentials. SSH is disabled in that image.')])

chapter('Shortcuts and edit safety',[],
 'The labels above the pads identify SHIFT event commands. These act on the current event selection or relevant Pattern target; they do not all operate on the Sound assignment.',
 table=[('Gesture','Result'),('SHIFT + pad 1 / 2','Undo / Redo.'),('SHIFT + pad 3 / 4','Step Undo / Step Redo (hardware labels COMPARE / SPLIT).'),('SHIFT + pad 5 / 6','Quantize 100% / 50%.'),('SHIFT + pad 7 / 8','Nudge selected/relevant events left / right.'),('SHIFT + pad 9','Clear only the selected Sound/pad events in this Pattern; keep its sample.'),('SHIFT + pad 10','Clear automation in the current target.'),('SHIFT + pad 11 / 12','Events: 11 copies explicitly selected notes; move the cursor, then 12 pastes there with original spacing. Without a note selection, copy all current pad events and paste at original Pattern positions.'),('SHIFT + pad 13 / 14','Transpose events -1 / +1 semitone.'),('SHIFT + pad 15 / 16','Transpose events -12 / +12 semitones.'),('SHIFT + ERASE + Sound pad','Reset the Sound slot, including its assignment.'),('SHIFT + MUTE','Choke all notes/voices/previews globally.')],
 notes=[('Before a destructive action','Check scope, Group, Sound, Pattern and selection. An inverted confirmation is a decision, not a status message. Read the prompt and use the labelled confirm/cancel action.'),
 ('Sampling shortcuts','SHIFT + SAMPLING opens Sample Edit; SHIFT + PAD MODE enables Keyboard; SHIFT + SELECT opens Events. Keep these separate from mode pinning.')])

chapter('Troubleshooting and a session checklist',[],
 'Most apparent silence or timing problems are easier to locate by checking the signal path and active states in a consistent order.',
 table=[('Symptom','Check in this order'),('No Sound','Interface and Main Output; Group/Scene clip; Sound/Group mute or solo; sample mapping; level.'),('Notes do not record','REC enabled; active Group Pattern; Pattern length; correct keyboard note; next loop.'),('A long delay after a pad','Bypass chain effects, especially look-ahead/tape processing; then check buffer and CPU.'),('Distorted recording','Input clipping; selected rate versus interface-supported rate; SR/BITS effects in the Sound.'),('Only one slice sounds','Mapped note zones and played note; correct target Sound; zone key/velocity limits.'),('Editor does not follow','FOLLOW enabled; current Pattern is active; transport playing; cursor edits have paused Follow.'),('Group is silent','Group mute, another Group solo, Scene clip empty, output route and selected Pattern.'),('USB file is missing','Media mounted; correct folder; WAV extension; relink unavailable external assets.')],
 notes=[('Before ending a session','Stop recording, save the project, collect samples if you will move it and back up the project/audio folder. Use an orderly system shutdown before removing power or changing the HAT.'),
 ('When reporting a problem','Record the controller, workspace name, Group/Pattern, audio interface, sample rate/buffer and exact gesture. A display photo and a minimal saved project make a reproducible report.'),
 ('Continue with the atlas','The following pages are a visual reference, not another tutorial. Captions identify the workspace and visible parameter bindings so you can match a screen to the workflow above.')])

SCREEN_HELP={
 'PAD':'Select Master, Group or Sound before editing level. This is the main control view, not the pad-mode configuration page.',
 'CHANNEL':'Output pages cover Audio, Aux 1 and Aux 2; Sound also has MIDI. Select the destination before changing its level.',
 'INPUT':'Choose a channel source, gain and monitor behaviour. Input belongs to Sound/Group scope; Master has no input module.',
 'GROOVE':'Adjust the amount and timing of groove for the selected scope. This is separate from destructive event quantization.',
 'MACRO':'Choose a macro, assign a compatible target or clear its assignment. The selected scope determines which macro set is edited.',
 'MACRO ASSIGN':'Select a compatible parameter target and APPLY. An empty list means no assignable target is currently available.',
 'SAMPLER':'Navigate parameter pages, then fields. Envelope type changes which controls are present. Play the Sound while adjusting.',
 'PLUGIN':'Parameters belong to the selected chain slot. SHIFT + BROWSE opens slot replacement/removal even when a plug-in is loaded.',
 'PLUGIN SLOTS':'Select a chain slot before copying, moving, bypassing or removing it. Instrument slots must remain first.',
 'PARAM NAV':'Preview the module and its subpage while NAV is held. Release NAV to enter that destination.',
 'BROWSE':'Turn to select a folder or WAV. Open folders, BACK goes up; PREHEAR auditions. Pads choose the receiving Sound.',
 'PLUGIN BROWSE':'Choose a compatible LV2 effect/instrument or the remove entry. Loading an occupied slot replaces that slot.',
 'PLUGIN MOVE':'Select the destination slot and confirm MOVE. Cancel returns without reordering the chain.',
 'PLUGIN SC':'Select a sidechain source only for a plug-in that exposes sidechain input. Feedback cycles are rejected.',
 'SAMPLING':'Select source, input and Detect/Sync options. START arms capture; STOP finishes it; CANCEL abandons the take.',
 'SAMPLING NAV':'Preview Record, Edit, Slice or Zone before releasing NAV. The subpage indicator follows the selected destination.',
 'SAMPLE EDIT':'START/END set playback or selection boundaries. Choose a process, check the range and confirm APPLY.',
 'CHOP':'Choose Split/Grid/Detect/Manual, audition cuts and use EDIT for boundaries. APPL.TO selects a destination.',
 'ZONE':'Choose the zone before changing its playback range, loop, tuning, envelope or key/velocity map.',
 'STRETCH':'Adjust stretch length and pitch, audition, then APPLY or cancel. This is a preview state until committed.',
 'SLICE TARGET':'Select Group and first Sound/all Sounds. SINGLE assigns only the selected slice. Check occupied destinations before APPLY.',
 'SAMPLE DELETE':'Choose REMOVE FROM PAD or DELETE FILE, then confirm. Assignment removal and physical file deletion are different operations.',
 'PAD CONFIG':'Choose Pad, Keyboard or 16 VEL. Fixed velocity affects performance; it is separate from zone gain or normalization.',
 'NOTE REPEAT':'Select rate and division, then hold pads. With playback running, repeat follows the musical grid.',
 'ARP':'Held keyboard notes feed the arpeggiator. Gate, direction, octave range and Hold change its performance behaviour.',
 'GROUP':'Select the Group in the current bank. Patterns and Sound focus follow that Group; Group output/mute can silence its whole kit.',
 'SELECT':'Focus quietly or choose multiple targets. Event selection and Sound selection are separate scopes.',
 'DUPLICATE':'Choose source and destination in the active object scope. The events option determines whether related musical data is copied.',
 'MUTE':'Sound pads toggle mute. Inspect Group state as well; muted audio is cut immediately.',
 'SOLO':'A solo state can silence otherwise unmuted channels. Use the displayed reset actions when troubleshooting silence.',
 'STEP':'Pads toggle steps for the selected Sound/note. Bank and Follow change the visible time window, not the Pattern length.',
 'PATTERN':'Pads select Patterns. LENGTH, DOUBLE and DUPLICATE affect the current Group Pattern. ENTER/EDITOR opens the event grid.',
 'PATTERN GRID':'Navigate time and row/pitch, mark a selection and open EDIT. Follow pauses when you move the edit cursor.',
 'GRID EDIT':'Change position, pitch, velocity, probability or duration for the active target set. DELETE asks for confirmation.',
 'EVENT':'Inspect the focused event in the compact event view. Previous/next moves the cursor; delete requires confirmation.',
 'OPTIONS':'Grid, quantize strength and swing have different purposes. Choose the intended tab before changing a value.',
 'RECORD SETTINGS':'Set metronome level, count-in length and recording quantize. SHIFT + GRID opens this workspace.',
 'RECORD PREPARE':'Hold REC for one second to prepare length/grid. Release REC to return to the prior view ready to record.',
 'MIDI TRACK':'Set the Sound note source, MIDI destination/channel and note behaviour for external instruments.',
 'VIEW NAV':'Adjust view zoom/scroll or choose the labelled destination. This is view navigation, not individual note editing.',
 'SCENE':'Pads recall Scenes. Each Scene holds Group Pattern references; change timing follows Perform Grid.',
 'SONG':'INSERT adds the selected Scene, PLAY toggles arrangement playback and DELETE removes the chosen entry after confirmation.',
 'SONG AUTO':'Choose a Song master-automation lane. Toggle it or remove it without deleting its Scene reference.',
 'MIXER':'Choose scope, then Level/Pan/Route. The meters show audio activity, not whether a Pattern contains notes.',
 'PROJECT':'SAVE stores the current project; LOAD chooses a saved slot; MANAGE exposes names, presets, relink and export.',
 'PROJECT LOAD':'Select a saved project and confirm loading. Shift actions rename/delete the selected slot; NEW begins name entry.',
 'PROJECT MANAGE':'Select an operation and OPEN. New, Rename and Save As have different effects on saved slots.',
 'PROJECT NAME':'Arrows move the cursor; the encoder changes a character. RANDOM suggests a name, SHIFT + CANCEL clears, OK commits.',
 'PRESET LOAD':'Choose a compatible Sound/Group preset and load it into the current target. Keep the target scope in mind.',
 'MISSING SAMPLES':'Search or browse for unavailable referenced audio. Scan again after connecting the missing USB source.',
 'RELINK RESULTS':'Review candidates before selecting a replacement. Browse manually when no exact match is found.',
 'RELINK BROWSE':'Navigate to the intended replacement WAV. Similar filenames are not proof that the audio is the same.',
 'SAMPLE RAM':'REFRESH queries loaded sample memory. PURGE frees unused sample data while playback/recording is stopped.',
 'EXPORT':'Choose range, source, format/depth and destination. Rendering is isolated from the live audio device.',
 'EXPORT DONE':'Read the output location and filename. BACK returns; NEW sets up another export.',
 'CONFIRM':'Read the full prompt before confirming. YES executes the operation; CANCEL keeps the current content.',
 'SETTINGS':'Choose Audio, MIDI or System, select the row and ENTER. Settings persist across restarts.',
 'SYSTEM':'The first page shows the Machinista logo/version. On Mikro, continue to CPU/RAM, then storage. On MK2 CPU/RAM is already on the right; following pages show storage.',
 'BLUETOOTH MIDI':'Enable, pair/scan and connect a MIDI device. This provides MIDI, not a Bluetooth audio stream.',
}

from tools.manual_updates_beta6 import en_update
en_update(CH,SCREEN_HELP)


def render_assets():
    catalog=[]
    with tempfile.TemporaryDirectory() as tmp:
        renderer=Mk2Renderer();color_renderer=Mk3Renderer()
        try:
            selected=[c for c in cases() if not c[0].startswith(('Notice /','SHIFT /','Group mute /','BLE /','Projects / EMPTY','Projects / LONG','Projects / BUSY','Automation /'))]
            selected=[c for c in selected if not c[0].startswith(('Compatibility /','Input / scope 0')) and not (c[2].get('capture_source')=='INTERNAL' and c[2].get('capture_section')==1)]
            selected += [('Grid / '+label,'OPTIONS',dict(grid_tab=tab)) for tab,label in ((0,'QUANT'),(1,'SWING'),(2,'STEP'))]
            selected += [('System / CPU cores','SYSTEM',dict(system_index=1,cpu_core_example=True))]
            selected += [('System / CPU','SYSTEM',dict(system_index=1)),('System / Storage 3','SYSTEM',dict(storage_bank=3)),('System / Storage 4','SYSTEM',dict(storage_bank=4))]
            selected += [('Tutorial / Custom chords','PAD CONFIG',dict(keyboard_enabled=True,pad_page=0,custom_chords=True)),('Tutorial / Chord edit','PAD CONFIG',dict(keyboard_enabled=True,pad_page=2,custom_chords=True)),('Tutorial / Chord variations','PAD CONFIG',dict(keyboard_enabled=True,pad_page=1,custom_chords=True))]
            selected += [('Tutorial / Slice zoom','CHOP',dict(slice_mode='MANUAL',slice_edit=True,wave_zoom=3,wave_offset=8000,slice_index=1)),('Tutorial / Keyboard','PAD CONFIG',dict(keyboard_enabled=True)),('Tutorial / Wave zoom','SAMPLE EDIT',dict(wave_zoom=2,wave_offset=8000))]
            selected += [('Tutorial / Events range','PATTERN GRID',dict(event_range_example=True)),('Tutorial / Ducktor','PLUGIN',dict(ducktor_example=True))]
            for i,(label,page,values) in enumerate(selected):
                a=fixture(tmp);p=Path(a.track()['sample']);p.parent.mkdir(parents=True,exist_ok=True)
                if not p.exists():
                    with wave.open(str(p),'wb') as wav:
                        wav.setparams((1,2,44100,0,'NONE','not compressed'))
                        wav.writeframes(array.array('h',(round(math.sin(j*.065)*math.exp(-(j%11025)/2300)*23000) for j in range(44100))).tobytes())
                a.project['name']='FIRST BEAT';a.track()['name']='Drum Loop';a.confirmation=('DELETE SELECTED?',lambda:None,'PATTERN GRID')
                a.track()['sampler']={'type':'ADSR','attack':12,'decay':300,'sustain':65,'release':180,'filter':'LP2','cutoff':2400}
                a.capture_stereo_peak=(.47,.39)
                from app.surface import PROCESSING
                a.process_index=PROCESSING.index('NORMALIZE')
                for row,times in ((0,(0,192)),(1,(96,288)),(2,(0,48,96,144,192,240,288,336))):
                    for tick in times:a.put_note(row,tick,dict(velocity=100,length=24,probability=100,note=36+row))
                s=Mk2Surface(a,ControllerInputs(a));apply(a,s,page,values)
                if values.get('cpu_core_example'):a.system_stats.update(cpu=40,cpu_cores=[dict(id=i,percent=value) for i,value in enumerate((100,35,10,15))])
                if values.get('keyboard_enabled'):
                    a.track().pop('slice_source',None);a.track().pop('slice_committed',None)
                    a.keyboard_root=60
                if values.get('custom_chords'):
                    a.track().pop('slice_source',None);a.track().pop('slice_committed',None)
                    a.performance().update(chord_mode='CUSTOM',custom_id='evening-keys',custom={'version':1,'name':'Evening Keys','root':60,'chords':[{'input':60,'name':'Cmaj7','notes':[60,64,67,71]},{'input':62,'name':'Dm7','notes':[62,65,69,72]}]},play={'strum':24,'direction':'UP','human_time':4,'velocity_spread':8,'velocity_direction':'UP','human_velocity':3})
                    a.chord_focus=0;a.pad_field=11 if values.get('pad_page')==2 else 2

                if values.get('event_range_example'):
                    a.pad=0;a.grid_notes=False;a.grid_step=0
                    a.held_buttons.add('SELECT');a.begin_grid_range();a.extend_grid_range(8)
                if values.get('ducktor_example'):
                    from app.ducktor import URI
                    from app.plugin_profiles import profile
                    meta=profile(URI);a.control_level=2;a.plugin_slot=0;a.plugin_param=0
                    a.plugin_catalog=[dict(uri=URI,name=meta['title'],kind='EFFECT',supported=True,builtin=True,ports=meta['parameters'])]
                    a.project['groups'][0]['pads'][1]['name']='Kick'
                    a.track()['name']='Bass'
                    a.track()['plugins']=[dict(uri=URI,kind='EFFECT',controls={v['symbol']:v['default'] for v in meta['parameters']},sidechain='SOUND 1')]
                s.waveform_window()
                if 'wave_zoom' in values:a.wave_zoom=values['wave_zoom'];a.wave_offset=values.get('wave_offset',0)
                if values.get('populated_plugins'):
                    a.plugin_catalog[0]['name']='Example LV2 Effect'
                    for j,port in enumerate(a.plugin_catalog[0]['ports']):port['name']='Control '+str(j+1)
                if page=='BROWSE':
                    (p.parent/'Library').mkdir(exist_ok=True)
                    a.browser.started=True;a.browser.directory=p.parent;a.browser.index=1
                # Cache only off-line, before requesting the final snapshot.
                path,first,last=s.waveform_window()
                if path:
                    renderer.waveforms.envelope(path,first,last)
                    if renderer.waveforms.future:renderer.waveforms.future.result()
                state=snapshot(s);left,right=renderer(state)
                def img(pix,w,invert=False):
                    im=Image.new('L',(w,64));im.putdata([(1-v if invert else v)*255 for v in pix]);return im.convert('RGB')
                pair=Image.new('RGB',(528,64),'#29231e');pair.paste(img(left,256),(0,0));pair.paste(img(right,256),(272,0))
                mk1=Mk1Surface(a,s.inputs);mk1.__dict__.update(s.__dict__)
                state1=snapshot(mk1);l1,r1=renderer(state1)
                pair1=Image.new('RGB',(528,64),'#29231e');pair1.paste(img(l1,256),(0,0));pair1.paste(img(r1,256),(272,0))
                first,last=a.wave_bounds(44100)
                env=read_envelope(p,start=first,end=last)
                if values.get('cpu_core_example'):a.system_index=2
                if page=='VIEW NAV':a.view_selector=True;a.view_index=-1;a.view_tool=None
                micro=img(frame(a,env),128,True)
                color_surface=Mk3Surface(a,s.inputs);color_surface.__dict__.update(s.__dict__)
                color_state=mk3_snapshot(color_surface)
                ref=color_state.get('wave') or color_state.get('sound_wave')
                if ref and ref[0]:
                    color_renderer.waveforms.envelope(ref[0],ref[1],ref[2],columns=460)
                    if color_renderer.waveforms.future:color_renderer.waveforms.future.result()
                color_pair=Image.new('RGB',(976,272),'#29231e')
                for j,image in enumerate(color_renderer.images(color_state)):color_pair.paste(image,(j*496,0))
                paths={}
                for device,im in [('mk2',pair),('mk1',pair1),('mikro',micro),('mk3',color_pair)]:
                    target=ASSETS/f'{i:03}-{device}.png'
                    im.resize((im.width*3,im.height*3),Image.Resampling.NEAREST).save(target)
                    paths[device]=str(target)
                fields=[(f[0],f[1]) for f in state.get('fields',[]) if f]
                catalog.append(dict(label=label,page=page,paths=paths,fields=fields,fields_by_device={'mk3':[(f[0],f[1]) for f in color_state['fields'] if f],'mk2':fields,'mk1':[(f[0],f[1]) for f in state1['fields'] if f]},hashes={'mk3':hashlib.sha256(color_pair.tobytes()).hexdigest(),'mk1':hashlib.sha256(pair1.tobytes()).hexdigest(),'mk2':hashlib.sha256(pair.tobytes()).hexdigest(),'mikro':hashlib.sha256(micro.tobytes()).hexdigest()}))
            from app.branding import boot_frame
            micro=img(boot_frame(128),128,True)
            pair=Image.new('RGB',(528,64),'#29231e')
            for x in (0,272):pair.paste(img(boot_frame(256),256),(x,0))
            paths={}
            for device,im in [('mikro',micro),('mk1',pair),('mk2',pair)]:
                target=ASSETS/f'startup-{device}.png';im.resize((im.width*3,im.height*3),Image.Resampling.NEAREST).save(target);paths[device]=str(target)
            paths['mk3']=catalog[0]['paths']['mk3']
            catalog.insert(0,dict(label='Startup / controller connected',page='STARTUP',paths=paths,fields=[],hashes={'mk3':catalog[0]['hashes']['mk3'],'mk1':hashlib.sha256(pair.tobytes()).hexdigest(),'mk2':hashlib.sha256(pair.tobytes()).hexdigest(),'mikro':hashlib.sha256(micro.tobytes()).hexdigest()}))
        finally:renderer.close();color_renderer.close()
    from tools.manual_native_synth import synth_catalog
    catalog.extend(synth_catalog(ASSETS))
    from tools.manual_native_effects import effect_catalog
    catalog.extend(effect_catalog(ASSETS))
    from tools.manual_clip_arranger import catalog as clip_catalog
    catalog.extend(clip_catalog(ASSETS))
    from tools.manual_controller_stems import catalog as stem_catalog
    catalog.extend(stem_catalog(ASSETS))
    (ASSETS/'catalog.json').write_text(json.dumps(catalog,indent=2))
    return catalog

def choose(value,device):
    text=value.get(device,value.get('mk2','')) if isinstance(value,dict) else value
    if device=='mk1':
        text=text.replace('MK2','MK1').replace('large master encoder','dedicated TEMPO encoder').replace('großen Master-Encoder','eigenen TEMPO-Regler')
        text=text.replace('press ENTER','use the labelled OPEN/LOAD action').replace('with ENTER','with the labelled display action').replace('mit ENTER','mit der beschrifteten Displayaktion')
    from tools.manual_controller_scope import scope_text
    if device=='mk3':
        from tools.manual_current import mk3_text
        text=mk3_text(text)
    from tools.manual_plain_language import simplify
    return simplify(scope_text(text,device),globals().get('MANUAL_LANGUAGE','en'))

class Manual:
    def __init__(self,device,catalog):
        self.device=device;self.catalog=catalog;self.name={'mikro':'Mikro MK1','mk1':'MK1','mk2':'MK2','mk3':'MK3 / Maschine+'}[device]
        self.path=OUT/f'Machinista_{"Mikro_MK1" if device=="mikro" else device.upper()}_User_Manual_EN.pdf'
        self.c=canvas.Canvas(str(self.path),pagesize=(W,H),pageCompression=1)
        self.c.setTitle('Machinista - '+self.name+' User Manual')
        self.c.setAuthor('Machinista project');self.c.setSubject('English workflow and display reference | 0.1.0-beta.19 | Fokus V2')
        self.page=0;self.links=[];self.overflow=[];self.atlas=[];self.chapter_pages={};self.atlas_start=None;self.flow_title=""
        seen=set()
        for item in catalog:
            if device=='mikro' and item['page'] in ('CONTRAST L','CONTRAST R'):continue
            if device!='mikro' and item['page'] in ('CONTRAST','PARAM NAV','SAMPLING NAV'):continue
            h=item['hashes'][device]
            if h in seen:continue
            seen.add(h);self.atlas.append(item)

    def text(self,text,x,y,width=CW,style=STYLE):
        p=Paragraph(text,style);_,height=p.wrap(width,H)
        if self.device=='mk3' and y-height<60 and y<H-80:
            self.end();self.begin(self.flow_title+' / continued','Workflow / reference');y=self.y
        p.drawOn(self.c,x,y-height)
        return y-height-style.spaceAfter

    def begin(self,title,section,key=None):
        self.page+=1;c=self.c
        c.setFillColor(ACCENT);c.rect(M,H-35,26,3,fill=1,stroke=0)
        c.setFillColor(MUTED);c.setFont('ManualBold',8)
        c.drawString(M+36,H-36,'MACHINISTA / '+self.name.upper())
        c.setFont('Manual',8);c.drawRightString(W-M,H-36,section.upper())
        c.setStrokeColor(LINE);c.line(M,43,W-M,43)
        c.setFillColor(MUTED);c.setFont('Manual',8);c.drawString(M,29,'User Manual  |  0.1.0-beta.19  |  English')
        c.drawRightString(W-M,29,str(self.page))
        if key:c.bookmarkPage(key);c.addOutlineEntry(title,key,0,False)
        self.y=self.text(escape(title),M,H-62,style=ParagraphStyle('title',parent=STYLE,fontName='ManualBold',fontSize=23,leading=27,spaceAfter=13))

    def end(self):
        if self.y<56:self.overflow.append((self.page,self.y))
        self.c.showPage()

    def shot(self,item,y,caption=None):
        c=self.c
        if self.device!='mikro':
            width=CW;height=width*(272/976 if self.device=='mk3' else 64/528)
            if self.device=='mk3' and y-height-35<60:
                self.end();self.begin(self.flow_title+' / continued','Workflow / reference');y=self.y
            c.drawImage(item['paths'][self.device],M,y-height,width,height)
            if caption:y=self.text(escape(caption),M,y-height-5,style=SMALL)
            else:y-=height+10
        else:
            width=202;height=101
            c.drawImage(item['paths'][self.device],M,y-height,width,height)
            if caption:self.text(escape(caption),M+220,y-5,width=CW-220,style=SMALL)
            y-=height+12
        return y

    def table(self,rows,y):
        st=ParagraphStyle('cell',parent=STYLE,fontSize=10.0,leading=13.7,spaceAfter=0)
        data=[[Paragraph(escape(str(v)),st) for v in row] for row in rows]
        t=Table(data,colWidths=[CW*.31,CW*.69],hAlign='LEFT')
        t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),PALE),('LINEBELOW',(0,0),(-1,0),.6,ACCENT),('LINEBELOW',(0,1),(-1,-1),.3,LINE),('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),8),('RIGHTPADDING',(0,0),(-1,-1),8),('TOPPADDING',(0,0),(-1,-1),6),('BOTTOMPADDING',(0,0),(-1,-1),6)]))
        _,height=t.wrap(CW,H);t.drawOn(self.c,M,y-height);return y-height-12

    def cover(self):
        self.page+=1;c=self.c;c.setFillColor(INK);c.rect(0,0,W,H,fill=1,stroke=0)
        c.setFillColor(ACCENT);c.rect(M,H-86,52,6,fill=1,stroke=0)
        brand=Image.open(ROOT/'assets/branding/machinista-logo.png').convert('RGBA')
        bbox=brand.getchannel('A').point(lambda v:255 if v>=128 else 0).getbbox();brand=brand.crop(bbox)
        c.setFillColor(white);c.roundRect(M,H-178,CW,92,8,fill=1,stroke=0)
        logo_width=CW-24;logo_height=logo_width*brand.height/brand.width
        c.drawImage(ImageReader(brand),M+12,H-132-logo_height/2,logo_width,logo_height,mask='auto')
        c.setFont('Manual',26);c.drawString(M,H-217,self.name)
        c.setFont('ManualBold',14);c.drawString(M,H-252,'USER MANUAL')
        c.setFont('Manual',12);c.drawString(M,H-275,'Workflows, controls and illustrated screen reference')
        item=next(x for x in self.catalog if x['page']=='SAMPLE EDIT')
        width=CW if self.device!='mikro' else 300;height=width*(272/976 if self.device=='mk3' else 64/528 if self.device!='mikro' else .5)
        c.drawImage(item['paths'][self.device],M,H-320-height,width,height)
        c.setFillColor(HexColor('#b8d2d6'));c.setFont('Manual',11)
        for i,line in enumerate(['Play. Record. Slice. Sequence. Arrange.','English edition','Machinista 0.1.0-beta.19 / Fokus V2','8 November 2026']):c.drawString(M,160-i*22,line)
        c.showPage()

    def contents(self):
        per=20;count=math.ceil(len(CH)/per);start=2+count
        self.workflow_start=start
        for bank in range(count):
            self.begin('Contents'+(' / continued' if bank else ''),'Guide')
            self.y=self.text('Select a chapter title to jump to it. The screen atlas follows the workflow chapters.',M,self.y)
            for i,ch in enumerate(CH[bank*per:(bank+1)*per],bank*per):
                number=getattr(self,'known_pages',{}).get(i,start+sum(1+len(prior.get('supplements',[])) for prior in CH[:i]));label=f'{i+1:02}  {ch["title"]}'
                self.c.setFont('Manual',10.2);self.c.setFillColor(INK);self.c.drawString(M,self.y-11,label)
                self.c.setFillColor(ACCENT);self.c.drawRightString(W-M,self.y-11,str(number))
                self.c.linkRect('',f'ch{i}',(M,self.y-17,W-M,self.y+1),relative=0,thickness=0)
                self.y-=27
            if bank==count-1:
                self.y-=12;self.y=self.text(f'<b>Screen atlas</b> begins on page {getattr(self,'known_atlas',None) or start+sum(1+len(item.get('supplements',[])) for item in CH)}. It includes a workspace index, actual display screenshots and controller-specific operating notes.',M,self.y)
                self.y=self.text('Notation: CAPITALS identify hardware buttons or displayed labels. A + means hold the first control while operating the next. Numbered steps describe the order of an operation.',M,self.y)
            self.end()

    def workflow_figure(self,title,page):
        preferred={
            ('Manual live chopping and Slice Edit','CHOP'):'Slice / MANUAL / edit',
            ('Zoom and scroll the waveform','CHOP'):'Tutorial / Slice zoom',
            ('Zoom and scroll the waveform','SAMPLE EDIT'):'Tutorial / Wave zoom',
            ('Keyboard, scales and 16 velocities','PAD CONFIG'):'Tutorial / Keyboard',
            ('LV2 plug-ins: add, replace and remove','PLUGIN'):'Plugins / PLUGIN / bank 1',
            ('Reading the displays','PLUGIN'):'Plugins / PLUGIN / bank 1',
            ('LV2 plug-ins: add, replace and remove','PLUGIN BROWSE'):'Plugins / PLUGIN BROWSE / bank 1',
        }.get((title,page))
        return next(x for x in self.catalog if x['label']==preferred) if preferred else next(x for x in self.catalog if x['page']==page)

    def controller_diagram(self,y):
        c=self.c;x=M;w=CW;h=172;c.setFillColor(PALE);c.roundRect(x,y-h,w,h,9,fill=1,stroke=0)
        c.setFillColor(INK);c.setFont('ManualBold',8)
        if self.device=='mikro':
            for i,t in enumerate(['F1','F2','F3']):c.drawCentredString(x+32+i*48,y-20,t)
            c.setFillColor(INK);c.roundRect(x+14,y-93,148,60,3,fill=1,stroke=0)
            c.setFillColor(white);c.setFont('Manual',9);c.drawCentredString(x+88,y-66,'128 x 64 DISPLAY')
            c.setFillColor(INK);c.circle(x+194,y-65,17,fill=0,stroke=1)
            c.setFont('Manual',8);c.drawString(x+12,y-111,'NAV      <       >       ENTER')
            c.drawString(x+12,y-135,'BROWSE   SAMPLING   GROUP')
            c.drawString(x+12,y-155,'MAIN / SHIFT / TRANSPORT')
            px=x+300;py=y-36
        elif self.device=='mk3':
            for i in range(8):c.drawCentredString(x+20+(i//4)*244+(i%4+.5)*56,y-20,str(i+1))
            for j in range(2):
                c.setFillColor(INK);c.roundRect(x+20+j*244,y-110,224,80,3,fill=1,stroke=0)
                c.setFillColor(white);c.setFont('Manual',9);c.drawCentredString(x+132+j*244,y-74,('LEFT' if j==0 else 'RIGHT')+' 480 x 272 / COLOR')
            c.setStrokeColor(ACCENT)
            for i in range(8):c.circle(x+20+(i//4)*244+(i%4+.5)*56,y-128,8,fill=0,stroke=1)
            c.setFillColor(INK);c.setFont('Manual',8)
            c.drawString(x+20,y-148,'CHANNEL / PLUG-IN / MIXER / EVENTS / SETTINGS')
            c.drawString(x+20,y-163,'4D PUSH / GROUP A-H / SMART STRIP / TRANSPORT')
            return y-h-14
        else:
            for i in range(8):c.drawCentredString(x+48+i*51,y-20,str(i+1))
            for j in range(2):
                c.setFillColor(INK);c.roundRect(x+20+j*244,y-85,224,50,3,fill=1,stroke=0)
                c.setFillColor(white);c.setFont('Manual',9);c.drawCentredString(x+132+j*244,y-64,('LEFT' if j==0 else 'RIGHT')+' DISPLAY 256 x 64')
            c.setFillColor(INK)
            for i in range(8):c.circle(x+48+i*51,y-105,8,fill=0,stroke=1)
            c.setFont('Manual',8);c.drawString(x+20,y-135,'CONTROL / STEP / BROWSE / SAMPLING     PAGE < >')
            c.drawString(x+20,y-155,'GROUP A-H    '+('VOLUME / SWING / TEMPO' if self.device=='mk1' else 'MASTER ENCODER')+'    TRANSPORT')
            return y-h-14
        c.setStrokeColor(ACCENT)
        for row in range(4):
            for col in range(4):
                xx=px+col*37;yy=py-row*32;c.roundRect(xx,yy-24,29,24,3,stroke=1,fill=0)
                c.setFillColor(INK);c.drawCentredString(xx+14.5,yy-16,str((3-row)*4+col+1))
        return y-h-14

    def workflow(self,i,ch):
        self.chapter_pages[i]=self.page+1;self.flow_title=f'{i+1:02}  '+ch['title']
        self.begin(self.flow_title,'Workflow / reference',f'ch{i}')
        self.y=self.text(escape(choose(ch['intro'],self.device)),M,self.y)
        if ch.get('source_title',ch['title'])=='Know your controller':self.y=self.controller_diagram(self.y-4)
        else:
            # One large figure, or a compact two-state strip, keeps prose legible.
            names=ch['screens'][:1 if self.device=='mk3' else 2]
            topic=ch.get('source_title',ch['title'])
            if self.device!='mikro':
                if topic=='Reading the displays':names=['SAMPLER'] if self.device=='mk3' else ['SAMPLER','PLUGIN']
                names=[name for name in names if name not in ('PARAM NAV','SAMPLING NAV')]
            if names:
                if self.device=='mikro' and len(names)>1:
                    for j,name in enumerate(names):
                        item=self.workflow_figure(ch.get('source_title',ch['title']),name)
                        xx=M+j*(CW/2);self.c.drawImage(item['paths']['mikro'],xx,self.y-85,170,85)
                        self.text(escape(name),xx,self.y-90,width=CW/2-10,style=SMALL)
                    self.y-=112
                else:
                    for name in names:
                        item=self.workflow_figure(ch.get('source_title',ch['title']),name)
                        self.y=self.shot(item,self.y,name)
        if ch.get('table'):self.y=self.table([[choose(v,self.device) for v in row] for row in ch['table']],self.y)
        for n,step in enumerate(ch['steps'],1):
            self.y=self.text(f'<b>{n}.</b> '+escape(choose(step,self.device)),M,self.y)
        for title,body in ch['notes']:
            if not choose(body,self.device):continue
            self.y=self.text('<b>'+escape(choose(title,self.device))+'.</b> '+escape(choose(body,self.device)),M,self.y,style=ParagraphStyle('note',parent=STYLE,fontSize=10.2,leading=14.4,spaceAfter=9))
        self.end()
        for supplement in ch.get('supplements',[]):self.supplement(i,supplement)

    def supplement(self,i,ch):
        self.flow_title=f'{i+1:02}  '+ch['title']
        self.begin(self.flow_title,'Workflow / reference')
        self.y=self.text(escape(choose(ch['intro'],self.device)),M,self.y)
        for label in ch.get('figures',[]):
            item=next(x for x in self.catalog if x['label']==label)
            self.y=self.shot(item,self.y)
        images=ch.get('images',[])
        if images==['power','ssh']:
            for col,name in enumerate(images):
                path=ROOT/'assets/manual-web'/f'{name}.png';image=Image.open(path)
                width=190;height=width*image.height/image.width
                self.c.drawImage(str(path),M+col*(CW/2),self.y-height,width,height)
            self.y-=215
        else:
            for name in images:
                path=ROOT/'assets/manual-web'/f'{name}.png'
                image=Image.open(path)
                width=min(CW,245 if image.width<image.height else CW)
                height=width*image.height/image.width
                if height>285:height=285;width=height*image.width/image.height
                self.c.drawImage(str(path),M,self.y-height,width,height)
                self.y-=height+10
        for n,step in enumerate(ch['steps'],1):
            self.y=self.text(f'<b>{n}.</b> '+escape(choose(step,self.device)),M,self.y)
        for title,body in ch.get('notes',[]):
            if not choose(body,self.device):continue
            self.y=self.text('<b>'+escape(choose(title,self.device))+'.</b> '+escape(choose(body,self.device)),M,self.y)
        self.end()

    def screen_atlas(self):
        self.atlas_start=self.page+1
        self.begin('Screen atlas / workspace index','Display reference','atlas')
        self.y=self.text('Find the workspace name in this index. Atlas figures preserve the actual display pixels. Not every illustrated state is reached by a separate button: many are parameter banks, temporary overlays or confirmation steps.',M,self.y)
        per=4 if self.device=='mikro' else 2 if self.device=='mk3' else 5
        # Index can span multiple pages, so compute its own page count first.
        bypage={}
        hash_page={item['hashes'][self.device]:i//per for i,item in enumerate(self.atlas)}
        for item in self.catalog:
            h=item['hashes'][self.device]
            if self.device=='mikro' and item['page'] in ('CONTRAST L','CONTRAST R'):continue
            if self.device!='mikro' and item['page'] in ('CONTRAST','PARAM NAV','SAMPLING NAV'):continue
            if h in hash_page:bypage.setdefault(item['page'],hash_page[h])
        keys=sorted(bypage);index_pages=math.ceil(len(keys)/44)
        atlas_first=self.page+index_pages
        for bank in range(index_pages):
            if bank:
                self.end();self.begin('Screen atlas / index continued','Display reference')
            for row,key in enumerate(keys[bank*44:(bank+1)*44]):
                col=row//22;r=row%22;xx=M+col*(CW/2);yy=self.y-r*24
                label=key;page=atlas_first+bypage[key]
                self.c.setFillColor(INK);self.c.setFont('Manual',8.6);self.c.drawString(xx,yy-12,label)
                self.c.setFillColor(ACCENT);self.c.drawRightString(xx+CW/2-16,yy-12,str(page))
                self.c.linkRect('',f'atlas{bypage[key]}',(xx,yy-18,xx+CW/2-12,yy+1),thickness=0)
            self.y-=550
        self.end()
        for bank in range(math.ceil(len(self.atlas)/per)):
            self.begin('Screen atlas / '+str(bank+1),'Display reference',f'atlas{bank}')
            for item in self.atlas[bank*per:(bank+1)*per]:
                title=item['label'].replace('scope 0','Master').replace('scope 1','Group').replace('scope 2','Sound')
                self.y=self.text(escape(title),M,self.y,style=HEAD)
                fields='  |  '.join(f'{k}: {v}' for k,v in item.get('fields_by_device',{}).get(self.device,item['fields']))
                if self.device=='mikro':
                    self.y=self.shot(item,self.y,'Workspace: '+item['page']+'. '+self.atlas_hint(item['page']))
                else:
                    self.y=self.shot(item,self.y)
                    if fields:self.y=self.text(escape(fields),M,self.y,style=SMALL)
                    else:self.y=self.text(escape(self.atlas_hint(item['page'])),M,self.y,style=SMALL)
                self.y-=8
            self.end()

    def atlas_hint(self,page):
        for family,pages in WORKFLOWS.items():
            if page in pages:return 'Context: '+family+'. '+choose(SCREEN_HELP.get(page,'Use the displayed action labels. In settings, choose the value with the encoder and return to the parent folder with ENTER.'),self.device)
        return 'A settings subpage; return to its parent folder when finished.'

    def finish(self):
        self.cover();self.contents()
        for i,ch in enumerate(CH):self.workflow(i,ch)
        self.screen_atlas()
        self.c.save()
        return dict(path=str(self.path),pages=self.page,atlas_screens=len(self.atlas),overflow=self.overflow)

def build(cls,device,catalog):
    manual=cls(device,catalog);result=manual.finish()
    if device=='mk3':
        corrected=cls(device,catalog);corrected.known_pages=manual.chapter_pages;corrected.known_atlas=manual.atlas_start
        result=corrected.finish()
        assert corrected.chapter_pages==manual.chapter_pages
    return result

if __name__=='__main__':
    from tools.manual_web_chords import enrich
    enrich(CH)
    from tools.manual_controller_scope import scope_chapters,system_hint
    scope_chapters(CH);SCREEN_HELP['SYSTEM']=system_hint()
    from tools.manual_audio_loops import enrich as enrich_audio
    enrich_audio(CH)
    from tools.manual_native_synth import enrich as enrich_synth
    enrich_synth(CH)
    from tools.manual_current import enrich as enrich_current
    enrich_current(CH)
    from tools.manual_plain_language import enrich as enrich_plain
    enrich_plain(CH)
    from tools.manual_native_effects import enrich as enrich_effects
    enrich_effects(CH)
    from tools.manual_clip_arranger import enrich as enrich_clips
    enrich_clips(CH)
    from tools.manual_controller_stems import enrich as enrich_stems
    enrich_stems(CH)
    from tools.manual_sample_sets import enrich as enrich_sets
    enrich_sets(CH)
    catalog=render_assets();results=[build(Manual,device,catalog) for device in ('mikro','mk1','mk2','mk3')]
    (ASSETS/'build-report.json').write_text(json.dumps(results,indent=2));print(json.dumps(results,indent=2))
    if any(x['overflow'] for x in results):sys.exit(2)
