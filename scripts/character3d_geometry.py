"""Small shared geometry operations; usable from Blender and ordinary Python."""
from collections import defaultdict
import numpy as np


def edge_loops(edges):
    links=defaultdict(list)
    for a,b in edges:
        links[int(a)].append(int(b));links[int(b)].append(int(a))
    if any(len(neighbours)!=2 for neighbours in links.values()):
        raise ValueError('Boundary is not a collection of closed edge loops')
    loops=[]
    while links:
        start=next(iter(links));loop=[start];previous=None;node=start
        while True:
            nxt=next(v for v in links[node] if v!=previous)
            if nxt==start:break
            loop.append(nxt);previous,node=node,nxt
        for node in loop:del links[node]
        loops.append(loop)
    return loops


def stitch_loops(a,b,vertices,axis,angular=False):
    axis=np.asarray(axis,dtype=float)
    center=(vertices[a].mean(axis=0)+vertices[b].mean(axis=0))*.5
    u=np.cross(axis,[0,0,1]);u/=max(np.linalg.norm(u),1e-10)
    if np.linalg.norm(u)<.1:
        u=np.cross(axis,[0,1,0]);u/=np.linalg.norm(u)
    v=np.cross(axis,u)
    def ordered(ids):
        ids=np.array(ids);q=vertices[ids]-center
        if np.sum(np.cross(q,np.roll(q,-1,axis=0)),axis=0)@axis<0:
            ids=ids[::-1];q=q[::-1]
        angles=np.mod(np.arctan2(q@v,q@u),2*np.pi)
        if angular:
            order=np.argsort(angles)
            return ids[order],angles[order]
        start=int(np.argmin(angles));ids=np.roll(ids,-start)
        lengths=np.linalg.norm(vertices[np.roll(ids,-1)]-vertices[ids],axis=1)
        progress=np.r_[0,np.cumsum(lengths[:-1])]/lengths.sum()*2*np.pi
        return ids,progress
    aa,at=ordered(a);bb,bt=ordered(b)
    i=j=0;tri=[]
    while i<len(aa) or j<len(bb):
        an=at[i+1] if i+1<len(aa) else at[0]+2*np.pi
        bn=bt[j+1] if j+1<len(bb) else bt[0]+2*np.pi
        if i>=len(aa):an=float('inf')
        if j>=len(bb):bn=float('inf')
        ai=aa[i%len(aa)];bj=bb[j%len(bb)]
        if an<bn:tri.append([ai,bj,aa[(i+1)%len(aa)]]);i+=1
        else:tri.append([ai,bj,bb[(j+1)%len(bb)]]);j+=1
    return np.array(tri)


def inside_polygon(points,polygon):
    x,y=points[:,0],points[:,1]
    inside=np.zeros(len(points),bool)
    for i in range(len(polygon)):
        a,b=polygon[i-1],polygon[i]
        crossing=(a[1]>y)!=(b[1]>y)
        denominator=b[1]-a[1]
        if abs(denominator)<1e-14:continue
        edge_x=(b[0]-a[0])*(y-a[1])/denominator+a[0]
        inside ^= crossing & (x<edge_x)
    return inside
