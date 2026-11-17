//@category Wave7
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import java.io.*;
import java.util.*;

public class TraceQseeNoCRoutes extends GhidraScript {
  public void run() throws Exception {
    String[] args=getScriptArgs();
    if (args.length!=1) throw new IllegalArgumentException("output file required");
    Set<Address> visited=new LinkedHashSet<>();
    DecompInterface di=new DecompInterface();
    di.toggleCCode(true);di.openProgram(currentProgram);
    try(PrintWriter out=new PrintWriter(new File(args[0]))) {
      for(long addrValue:new long[]{
          0x4a6b6759L, // error decode log
          0x4a6b6753L, // PCNOC
          0x4a6b6795L, // SNOC
          0x4a6b679aL, // MEMNOC
          0x4a6b67a1L, // NSSNOC
          0x4a6c9aa8L, // PCNOC noc-info data
          0x4a6c9b40L, // SNOC data
          0x4a6c9bd8L, // MEMNOC data
          0x4a6c9c70L  // NSSNOC data
      }) {
        Address ad=toAddr(addrValue);
        out.println("TARGET "+ad+" "+currentProgram.getListing().getDataContaining(ad));
        ReferenceIterator ri=currentProgram.getReferenceManager().getReferencesTo(ad);
        int count=0;
        while(ri.hasNext()){
          Reference rr=ri.next(); count++;
          Function f=getFunctionContaining(rr.getFromAddress());
          out.println("  REF "+rr.getFromAddress()+" "+rr.getReferenceType()+" FUNC "+(f==null?"none":f.getEntryPoint()));
          if(f!=null)visited.add(f.getEntryPoint());
          if(count>=40)break;
        }
        out.println("TOTAL_REFERENCES_LISTED "+count);
      }
      int count=0;
      for(Address a:visited){
        if(count++>=16) break;
        Function f=getFunctionAt(a);
        if(f==null)continue;
        out.println("\n--- FUNCTION "+a+" "+f.getName()+" ---");
        DecompileResults r=di.decompileFunction(f,35,monitor);
        out.println(r.decompileCompleted() ? r.getDecompiledFunction().getC() : "ERROR "+r.getErrorMessage());
      }
    }
    di.dispose();
  }
}
