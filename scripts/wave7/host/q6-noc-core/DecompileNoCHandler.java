//@category Wave7
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.SourceType;
import java.io.*;

public class DecompileNoCHandler extends GhidraScript {
 public void run() throws Exception {
  String[] args=getScriptArgs();
  if(args.length!=1)throw new IllegalArgumentException("output file");
  Address first=toAddr(0xb032a670L);
  Address last=toAddr(0xb032a99cL);
  Function f=currentProgram.getFunctionManager().getFunctionContaining(first);
  try(PrintWriter out=new PrintWriter(new File(args[0]))) {
   out.printf("PROGRAM %s, %s%n",currentProgram.getName(),currentProgram.getLanguageID());
   out.printf("HANDLER %s..%s EXISTING %s%n",first,last,f);
   if(f==null) {
    AddressSet body=new AddressSet(first,last);
    f=currentProgram.getFunctionManager().createFunction(
      "noc_error_capture_clear_report",
      currentProgram.getGlobalNamespace(),
      first,body,SourceType.USER_DEFINED);
   }
   out.printf("FUNCTION %s%n",f);
   if(f==null)throw new IllegalStateException("NoC function could not be defined");
   DecompInterface d=new DecompInterface();
   d.toggleCCode(true);d.openProgram(currentProgram);
   DecompileResults result=d.decompileFunction(f,90,monitor);
   out.printf("DECOMPILED %s ERROR %s%n",result.decompileCompleted(),result.getErrorMessage());
   if(result.decompileCompleted()&&result.getDecompiledFunction()!=null)
    out.println(result.getDecompiledFunction().getC());
   d.dispose();
  }
 }
}
