import pcbnew,json
b=pcbnew.LoadBoard('D:/apriltag-proccessor/render/work/apriltag_cam.kicad_pcb')
out={}
for f in b.GetFootprints():
    r=f.GetReference()
    if r in('U1','U2','U10','Y2','J1','LH1','TP1'):
        pads=[]
        for pd in f.Pads():
            q=pd.GetFPRelativePosition(); s=pd.GetSize()
            pads.append([pd.GetNumber(),round(q.x/1e6,4),round(q.y/1e6,4),round(s.x/1e6,3),round(s.y/1e6,3),int(pd.GetAttribute()),round(pd.GetDrillSizeX()/1e6,3)])
        out[r]=dict(fp=f.GetFPIDAsString(),side=f.GetLayerName(),rot=f.GetOrientationDegrees(),pads=pads)
        if r in ('U2','J1','Y2'): print(r,pads[:30])
json.dump(out,open('D:/apriltag-proccessor/render/work/localpads.json','w'))
