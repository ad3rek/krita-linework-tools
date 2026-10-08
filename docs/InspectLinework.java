// SPDX-License-Identifier: GPL-3.0-or-later
// Inspect user-provided executable metadata and feature strings; no patching.
// @category Analysis
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import java.util.regex.Pattern;
import java.io.PrintWriter;

public class InspectLinework extends GhidraScript {
 public void run() throws Exception {
  String[] args=getScriptArgs();
  PrintWriter out=new PrintWriter(args[0]);
  out.println("Program: "+currentProgram.getName());
  out.println("Language: "+currentProgram.getLanguageID());
  out.println("Executable: "+currentProgram.getExecutableFormat());
  out.println("Functions identified: "+currentProgram.getFunctionManager().getFunctionCount());
  Pattern pattern=Pattern.compile("(?i)(linework|pressure|bezier|control point|stroke weight|vector|curve tool|minimum size)");
  DataIterator data=currentProgram.getListing().getDefinedData(true);
  int count=0;
  while(data.hasNext() && !monitor.isCancelled()) {
   Data item=data.next(); Object value=item.getValue();
   if(value instanceof String && pattern.matcher((String)value).find()) {
    String s=((String)value).replace('\n',' ').replace('\r',' ');
    if(s.length()>240) s=s.substring(0,240);
    out.println(item.getAddress()+" | "+s);
    ReferenceIterator refs=currentProgram.getReferenceManager().getReferencesTo(item.getAddress());
    int n=0;
    while(refs.hasNext() && n++<5) {
     Reference ref=refs.next();
     Function f=currentProgram.getFunctionManager().getFunctionContaining(ref.getFromAddress());
     out.println("  ref "+ref.getFromAddress()+" function "+(f==null?"unknown":f.getName()));
    }
    count++;
   }
  }
  out.println("Matching feature strings: "+count);
  out.close();
  println("Linework feature inventory written. Matches: "+count);
 }
}
