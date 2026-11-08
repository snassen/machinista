import socket,struct,sys
def pad(b):return b+b"\0"*(4-len(b)%4)
def osc(addr,*ints):return pad(addr.encode())+pad((","+"i"*len(ints)).encode())+b"".join(struct.pack(">i",i) for i in ints)
s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
s.sendto(osc(sys.argv[1],*map(int,sys.argv[2:])),("127.0.0.1",int(__import__("os").environ.get("PORT","10111"))))
