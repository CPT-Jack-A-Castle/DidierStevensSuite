#!/usr/bin/env python

__description__ = 'EML dump utility'
__author__ = 'Didier Stevens'
__version__ = '0.0.3'
__date__ = '2015/09/21'

"""

Source code put in public domain by Didier Stevens, no Copyright
https://DidierStevens.com
Use at your own risk

History:
  2014/02/01: start
  2015/03/01: added Multipart flag
  2015/05/08: 0.0.2 added ZIP support
  2015/05/20: 0.0.3 added length; added type selection
  2015/06/08: Fix HexAsciiDump; added YARA support
  2015/09/12: added option -c
  2015/09/14: added option -m
  2015/09/21: reviewed man

Todo:
"""

import optparse
import email
import hashlib
import signal
import sys
import os
import zipfile
import re
import binascii
import textwrap
try:
    import yara
except:
    pass

MALWARE_PASSWORD = 'infected'

def PrintManual():
    manual = '''
Manual:

emldump is a tool to analyze MIME files.
The MIME file can be provided as an argument, via stdin (piping) and it may also be contained in a (password protected) ZIP file.
When emldump runs on a MIME file without any options, it reports the different parts in the MIME file. Like in this example:

emldump.py sample.vir
1: M         multipart/alternative
2:       610 text/plain
3: M         multipart/related
4:      1684 text/html
5:    133896 application/octet-stream

The first number is an index added by emldump (this index does not come from the MIME file). This index can be used to select a part.
If a part has an M indicator, then it is a multipart and can not be selected.
Next is the number of bytes in the part, and the MIME type of the part.

Some MIME files start with an info line that has to be skipped. For example e-mails saved with Lotus Notes. Skipping this first line can be done with option -H.

A particular part of the MIME file can be selected for further analysis with option -s. Here is an example where we use the index 2 to select the second part:

emldump.py sample.vir -s 2
00000000: 20 20 20 0D 0A 20 20 20 41 20 63 6F 70 79 20 6F     ..   A copy o
00000010: 66 20 79 6F 75 72 20 41 44 50 20 54 6F 74 61 6C  f your ADP Total
00000020: 53 6F 75 72 63 65 20 50 61 79 72 6F 6C 6C 20 49  Source Payroll I
00000030: 6E 76 6F 69 63 65 20 66 6F 72 20 74 68 65 20 66  nvoice for the f
00000040: 6F 6C 6C 6F 77 69 6E 67 20 70 61 79 72 6F 6C 6C  ollowing payroll
...

When a part is selected, by default the content of the part is dumped in HEX/ASCII format (option -a). An hexdump can be obtained with option -x, like in this example:
 
emldump.py sample.vir -s 2 -x
20 20 20 0D 0A 20 20 20 41 20 63 6F 70 79 20 6F
66 20 79 6F 75 72 20 41 44 50 20 54 6F 74 61 6C
53 6F 75 72 63 65 20 50 61 79 72 6F 6C 6C 20 49
6E 76 6F 69 63 65 20 66 6F 72 20 74 68 65 20 66
6F 6C 6C 6F 77 69 6E 67 20 70 61 79 72 6F 6C 6C
20 69 73 09 20 20 20 69 73 20 61 74 74 61 63 68

The raw content of the part can be dumped too with option -d. This can be used to redirect to a file or piped into another analysis program.

Option -s (select) takes an index number, but can also take a MIME type, like in this example:
emldump.py sample.vir -s text/plain

emldump can scan the content of the parts with YARA rules (the YARA Python module must be installed). You provide the YARA rules with option -y. You can provide one file with YARA rules, an at-file (@file containing the filenames of the YARA files) or a directory. In case of a directory, all files inside the directory are read as YARA files. All parts are scanned with the provided YARA rules, you can not use option -s to select an individual part.

Content of example.eml:
emldump.py example.eml
1: M         multipart/mixed
2:        32 text/plain
3:    114704 application/octet-stream

YARA example:
emldump.py -y contains_pe_file.yara example.eml
3:    114704 application/octet-stream contains_pe_file.yara Contains_PE_File

In this example, you use YARA rule contains_pe_file.yara to find PE files (executables) inside MIME files. The rule triggered for part 3, because it contains an EXE file encoded in BASE64.

If you want more information about what was detected by the YARA rule, use option --yarastrings like in this example:
emldump.py -y contains_pe_file.yara --yarastrings example.eml
3:    114704 application/octet-stream contains_pe_file.yara Contains_PE_File
 000010 $a 4d5a 'MZ'
 0004e4 $a 4d5a 'MZ'
 01189f $a 4d5a 'MZ'
 
YARA rule contains_pe_file detects PE files by finding string MZ followed by string PE at the correct offset (AddressOfNewExeHeader).
The rule looks like this:
rule Contains_PE_File
{
    meta:
        author = "Didier Stevens (https://DidierStevens.com)"
        description = "Detect a PE file inside a byte sequence"
        method = "Find string MZ followed by string PE at the correct offset (AddressOfNewExeHeader)"
    strings:
        $a = "MZ"
    condition:
        for any i in (1..#a): (uint32(@a[i] + uint32(@a[i] + 0x3C)) == 0x00004550)
}

maldoc.yara are YARA rules to detect shellcode, based on Frank Boldewin's shellcode detector used in OfficeMalScanner.

When looking for traces of Windows executable code (PE files, shellcode, ...) with YARA rules, one must take into account the fact that the executable code might have been encoded (for example via XOR and a key) to evade detection.
To deal with this possibility, emldump supports decoders. A decoder is another type of plugin, that will bruteforce a type of encoding on each part. For example, decoder_xor1 will encode each part via XOR and a key of 1 byte. So effectively, 256 different encodings of the part will be scanned by the YARA rules. 256 encodings because: XOR key 0x00, XOR key 0x01, XOR key 0x02, ..., XOR key 0xFF
Here is an example:
emldump.py -y contains_pe_file.yara -D decoder_xor1 example-xor.eml
3:    114704 application/octet-stream contains_pe_file.yara Contains_PE_File (XOR 1 byte key 0x14)

The YARA rule triggers on part 3. It contains a PE file encoded via XORing each byte with 0x14.

You can specify more than one decoder separated by a comma ,.
emldump.py -y contains_pe_file.yara -D decoder_xor1,decoder_rol1,decoder_add1 example-xor.eml
3:    114704 application/octet-stream contains_pe_file.yara Contains_PE_File (XOR 1 byte key 0x14)

Some decoders take options, to be provided with option --decoderoptions.

Option -c (--cut) allows for the partial selection of a stream. Use this option to "cut out" part of the stream.
The --cut option takes an argument to specify which section of bytes to select from the stream. This argument is composed of 2 terms separated by a colon (:), like this:
termA:termB
termA and termB can be:
- nothing (an empty string)
- a positive number; example: 10
- an hexadecimal number (to be preceded by 0x); example: 0x10
- a case sensitive string to search for (surrounded by square brackets and single quotes); example: ['MZ']
- an hexadecimal string to search for (surrounded by square brackets); example: [d0cf11e0]
If termA is nothing, then the cut section of bytes starts with the byte at position 0.
If termA is a number, then the cut section of bytes starts with the byte at the position given by the number (first byte has index 0).
If termA is a string to search for, then the cut section of bytes starts with the byte at the position where the string is first found. If the string is not found, the cut is empty (0 bytes).
If termB is nothing, then the cut section of bytes ends with the last byte.
If termB is a number, then the cut section of bytes ends with the byte at the position given by the number (first byte has index 0).
When termB is a number, it can have suffix letter l. This indicates that the number is a length (number of bytes), and not a position.
If termB is a string to search for, then the cut section of bytes ends with the last byte at the position where the string is first found. If the string is not found, the cut is empty (0 bytes).
No checks are made to assure that the position specified by termA is lower than the position specified by termB. This is left up to the user.
Examples:
This argument can be used to dump the first 256 bytes of a PE file located inside the stream: ['MZ']:0x100l
This argument can be used to dump the OLE file located inside the stream: [d0cf11e0]:
When this option is not used, the complete stream is selected. 
'''
    for line in manual.split('\n'):
        print(textwrap.fill(line, 78))

#Convert 2 Bytes If Python 3
def C2BIP3(string):
    if sys.version_info[0] > 2:
        return bytes([ord(x) for x in string])
    else:
        return string

def File2String(filename):
    try:
        f = open(filename, 'rb')
    except:
        return None
    try:
        return f.read()
    except:
        return None
    finally:
        f.close()

def FixPipe():
    try:
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    except:
        pass

dumplinelength = 16

# CIC: Call If Callable
def CIC(expression):
    if callable(expression):
        return expression()
    else:
        return expression

# IFF: IF Function
def IFF(expression, valueTrue, valueFalse):
    if expression:
        return CIC(valueTrue)
    else:
        return CIC(valueFalse)

def IsNumeric(str):
    return re.match('^[0-9]+', str)

def YARACompile(fileordirname):
    dFilepaths = {}
    if os.path.isdir(fileordirname):
        for root, dirs, files in os.walk(fileordirname):
            for file in files:
                filename = os.path.join(root, file)
                dFilepaths[filename] = filename
    else:
        for filename in ProcessAt(fileordirname):
            dFilepaths[filename] = filename
    return yara.compile(filepaths=dFilepaths)

def AddDecoder(cClass):
    global decoders

    decoders.append(cClass)

class cDecoderParent():
    pass

def LoadDecoders(decoders, verbose):
    if decoders == '':
        return
    scriptPath = os.path.dirname(sys.argv[0])
    for decoder in sum(map(ProcessAt, decoders.split(',')), []):
        try:
            if not decoder.lower().endswith('.py'):
                decoder += '.py'
            if os.path.dirname(decoder) == '':
                if not os.path.exists(decoder):
                    scriptDecoder = os.path.join(scriptPath, decoder)
                    if os.path.exists(scriptDecoder):
                        decoder = scriptDecoder
            exec open(decoder, 'r') in globals(), globals()
        except Exception as e:
            print('Error loading decoder: %s' % decoder)
            if verbose:
                raise e

class cIdentity(cDecoderParent):
    name = 'Identity function decoder'

    def __init__(self, stream, options):
        self.stream = stream
        self.options = options
        self.available = True

    def Available(self):
        return self.available

    def Decode(self):
        self.available = False
        return self.stream

    def Name(self):
        return ''

def File2Strings(filename):
    try:
        f = open(filename, 'r')
    except:
        return None
    try:
        return map(lambda line:line.rstrip('\n'), f.readlines())
    except:
        return None
    finally:
        f.close()

def ProcessAt(argument):
    if argument.startswith('@'):
        strings = File2Strings(argument[1:])
        if strings == None:
            raise Exception('Error reading %s' % argument)
        else:
            return strings
    else:
        return [argument]

class cDumpStream():
    def __init__(self):
        self.text = ''

    def Addline(self, line):
        if line != '':
            self.text += line + '\n'

    def Content(self):
        return self.text

def HexDump(data):
    oDumpStream = cDumpStream()
    hexDump = ''
    for i, b in enumerate(data):
        if i % dumplinelength == 0 and hexDump != '':
            oDumpStream.Addline(hexDump)
            hexDump = ''
        hexDump += IFF(hexDump == '', '', ' ') + '%02X' % ord(b)
    oDumpStream.Addline(hexDump)
    return oDumpStream.Content()

def CombineHexAscii(hexDump, asciiDump):
    if hexDump == '':
        return ''
    return hexDump + '  ' + (' ' * (3 * (16 - len(asciiDump)))) + asciiDump

def HexAsciiDump(data):
    oDumpStream = cDumpStream()
    hexDump = ''
    asciiDump = ''
    for i, b in enumerate(data):
        if i % dumplinelength == 0:
            if hexDump != '':
                oDumpStream.Addline(CombineHexAscii(hexDump, asciiDump))
            hexDump = '%08X:' % i
            asciiDump = ''
        hexDump+= ' %02X' % ord(b)
        asciiDump += IFF(ord(b) >= 32, b, '.')
    oDumpStream.Addline(CombineHexAscii(hexDump, asciiDump))
    return oDumpStream.Content()

#Fix for http://bugs.python.org/issue11395
def StdoutWriteChunked(data):
    while data != '':
        sys.stdout.write(data[0:10000])
        sys.stdout.flush()
        data = data[10000:]

CUTTERM_NOTHING = 0
CUTTERM_POSITION = 1
CUTTERM_FIND = 2
CUTTERM_LENGTH = 3

def ParseCutTerm(argument):
    if argument == '':
        return CUTTERM_NOTHING, None, ''
    oMatch = re.match(r'0x([0-9a-f]+)', argument, re.I)
    if oMatch == None:
        oMatch = re.match(r'(\d+)', argument)    
    else:
        return CUTTERM_POSITION, int(oMatch.group(1), 16), argument[len(oMatch.group(0)):]
    if oMatch == None:
        oMatch = re.match(r'\[([0-9a-f]+)\]', argument, re.I)
    else:
        return CUTTERM_POSITION, int(oMatch.group(1)), argument[len(oMatch.group(0)):]
    if oMatch == None:
        oMatch = re.match(r"\[\'(.+)\'\]", argument)
    else:
        if len(oMatch.group(1)) % 2 == 1:
            raise
        else:
            return CUTTERM_FIND, binascii.a2b_hex(oMatch.group(1)), argument[len(oMatch.group(0)):]
    if oMatch == None:
        return None, None, argument
    else:
        return CUTTERM_FIND, oMatch.group(1), argument[len(oMatch.group(0)):]

def ParseCutArgument(argument):
    type, value, remainder = ParseCutTerm(argument.strip())
    if type == CUTTERM_NOTHING:
        return CUTTERM_NOTHING, None, CUTTERM_NOTHING, None
    elif type == None:
        if remainder.startswith(':'):
            typeLeft = CUTTERM_NOTHING
            valueLeft = None
            remainder = remainder[1:]
        else:
            return None, None, None, None
    else:
        typeLeft = type
        valueLeft = value
        if remainder.startswith(':'):
            remainder = remainder[1:]
        else:
            return None, None, None, None
    type, value, remainder = ParseCutTerm(remainder)
    if type == CUTTERM_POSITION and remainder == 'l':
        return typeLeft, valueLeft, CUTTERM_LENGTH, value
    elif type == None or remainder != '':
        return None, None, None, None
    else:
        return typeLeft, valueLeft, type, value

def CutData(stream, cutArgument):
    if cutArgument == '':
        return stream

    typeLeft, valueLeft, typeRight, valueRight = ParseCutArgument(cutArgument)

    if typeLeft == None:
        return stream

    if typeLeft == CUTTERM_NOTHING:
        positionBegin = 0
    elif typeLeft == CUTTERM_POSITION:
        positionBegin = valueLeft
    else:
        positionBegin = stream.find(valueLeft)
        if positionBegin == -1:
            return ''

    if typeRight == CUTTERM_NOTHING:
        positionEnd = len(stream)
    elif typeRight == CUTTERM_POSITION:
        positionEnd = valueRight + 1
    elif typeRight == CUTTERM_LENGTH:
        positionEnd = positionBegin + valueRight
    else:
        positionEnd = stream.find(valueRight)
        if positionEnd == -1:
            return ''
        else:
            positionEnd += len(valueRight)

    return stream[positionBegin:positionEnd]

def EMLDump(emlfilename, options):
    FixPipe()
    if emlfilename == '':
        if sys.platform == 'win32':
            import msvcrt
            msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
        data = sys.stdin.read()
    elif emlfilename.lower().endswith('.zip'):
        oZipfile = zipfile.ZipFile(emlfilename, 'r')
        oZipContent = oZipfile.open(oZipfile.infolist()[0], 'r', C2BIP3(MALWARE_PASSWORD))
        data = oZipContent.read()
        oZipContent.close()
        oZipfile.close()
    else:
        data = File2String(emlfilename)

    global decoders
    decoders = []
    LoadDecoders(options.decoders, True)

    if options.yara != None:
        if not 'yara' in sys.modules:
            print('Error: option yara requires the YARA Python module.')
            return
        rules = YARACompile(options.yara)

    if options.header:
        data = data[data.find('\n') + 1:]
    oEML = email.message_from_string(data)

    if options.select == '':
        if options.yara == None:
            counter = 1
            for oPart in oEML.walk():
                data = oPart.get_payload(decode=True)
                if data == None:
                    lengthString = '       '
                else:
                    lengthString = '%7d' % len(data)
                print('%d: %s %s %s' % (counter, IFF(oPart.is_multipart(), 'M', ' '), lengthString, oPart.get_content_type()))
                counter += 1
        else:
            counter = 1
            for oPart in oEML.walk():
                data = oPart.get_payload(decode=True)
                if data != None:
                    oDecoders = [cIdentity(data, None)]
                    for cDecoder in decoders:
                        try:
                            oDecoder = cDecoder(data, options.decoderoptions)
                            oDecoders.append(oDecoder)
                        except Exception as e:
                            print('Error instantiating decoder: %s' % cDecoder.name)
                            if options.verbose:
                                raise e
                            return
                    for oDecoder in oDecoders:
                        while oDecoder.Available():
                            for result in rules.match(data=oDecoder.Decode()):
                                lengthString = '%7d' % len(data)
                                decoderName = oDecoder.Name()
                                if decoderName != '':
                                    decoderName = ' (%s)' % decoderName
                                print('%d: %s %s %-20s %s %s%s' % (counter, IFF(oPart.is_multipart(), 'M', ' '), lengthString, oPart.get_content_type(), result.namespace, result.rule, decoderName))
                                if options.yarastrings:
                                    for stringdata in result.strings:
                                        print(' %06x %s %s %s' % (stringdata[0], stringdata[1], binascii.hexlify(stringdata[2]), repr(stringdata[2])))
                counter += 1

    else:
        if options.dump:
            DumpFunction = lambda x:x
            if sys.platform == 'win32':
                import msvcrt
                msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)
        elif options.hexdump:
            DumpFunction = HexDump
        else:
            DumpFunction = HexAsciiDump
        counter = 1
        for oPart in oEML.walk():
            if IsNumeric(options.select) and counter == int(options.select) or not IsNumeric(options.select) and oPart.get_content_type() == options.select:
                if not oPart.is_multipart():
                    StdoutWriteChunked(DumpFunction(CutData(oPart.get_payload(decode=True), options.cut)))
                else:
                    print('Warning: you selected a multipart stream')
                break
            counter += 1

def Main():
    oParser = optparse.OptionParser(usage='usage: %prog [options] [mimefile]\n' + __description__, version='%prog ' + __version__)
    oParser.add_option('-m', '--man', action='store_true', default=False, help='Print manual')
    oParser.add_option('-d', '--dump', action='store_true', default=False, help='perform dump')
    oParser.add_option('-x', '--hexdump', action='store_true', default=False, help='perform hex dump')
    oParser.add_option('-a', '--asciidump', action='store_true', default=False, help='perform ascii dump')
    oParser.add_option('-H', '--header', action='store_true', default=False, help='skip first line')
    oParser.add_option('-s', '--select', default='', help='select item nr or MIME type for dumping')
    oParser.add_option('-y', '--yara', help="YARA rule file (or directory or @file) to check streams (YARA search doesn't work with -s option)")
    oParser.add_option('--yarastrings', action='store_true', default=False, help='Print YARA strings')
    oParser.add_option('-D', '--decoders', type=str, default='', help='decoders to load (separate decoders with a comma , ; @file supported)')
    oParser.add_option('--decoderoptions', type=str, default='', help='options for the decoder')
    oParser.add_option('-v', '--verbose', action='store_true', default=False, help='verbose output with decoder errors')
    oParser.add_option('-c', '--cut', type=str, default='', help='cut data')
    (options, args) = oParser.parse_args()

    if options.man:
        oParser.print_help()
        PrintManual()
        return

    if ParseCutArgument(options.cut)[0] == None:
        print('Error: the expression of the cut option (-c) is invalid: %s' % options.cut)
        return 0

    if len(args) > 1:
        oParser.print_help()
        print('')
        print('  Source code put in the public domain by Didier Stevens, no Copyright')
        print('  Use at your own risk')
        print('  https://DidierStevens.com')
        return
    elif len(args) == 1:
        EMLDump(args[0], options)
    else:
        EMLDump('', options)

if __name__ == '__main__':
    Main()
