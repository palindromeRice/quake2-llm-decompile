// Headless export of every non-external function: signature, decompiled C,
// disassembly, callers/callees. One JSON object per line.
// Usage (postScript): ExportFunctions.java <out.jsonl>
//@category Export

import com.google.gson.Gson;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.Function;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.mem.MemoryBlock;
import ghidra.program.model.symbol.Reference;

import java.io.PrintWriter;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

public class ExportFunctions extends GhidraScript {
    @Override
    public void run() throws Exception {
        String out = getScriptArgs()[0];
        DecompInterface dec = new DecompInterface();
        dec.openProgram(currentProgram);
        Gson gson = new Gson();
        try (PrintWriter w = new PrintWriter(out, "UTF-8")) {
            for (Function f : currentProgram.getFunctionManager().getFunctions(true)) {
                if (f.isExternal() || f.isThunk()) continue;
                Map<String, Object> rec = new LinkedHashMap<>();
                rec.put("address", f.getEntryPoint().toString());
                rec.put("name", f.getName());
                rec.put("signature", f.getPrototypeString(false, false));
                rec.put("calling_convention", f.getCallingConventionName());
                List<String> asm = new ArrayList<>();
                for (Instruction i : currentProgram.getListing().getInstructions(f.getBody(), true))
                    asm.add(i.getAddress() + "  " + i.toString());
                rec.put("disassembly", asm);
                // Constants the code reads from initialized memory (e.g. .rodata floats).
                Map<String, String> data = new LinkedHashMap<>();
                for (Instruction i : currentProgram.getListing().getInstructions(f.getBody(), true))
                    for (Reference ref : i.getReferencesFrom()) {
                        Address a = ref.getToAddress();
                        if (!ref.getReferenceType().isData() || !a.isMemoryAddress()) continue;
                        MemoryBlock b = currentProgram.getMemory().getBlock(a);
                        if (b == null || !b.isInitialized() || b.isExecute()) continue;
                        byte[] buf = new byte[8];
                        int n = currentProgram.getMemory().getBytes(a, buf);
                        long raw = 0;
                        for (int k = n - 1; k >= 0; k--) raw = (raw << 8) | (buf[k] & 0xff);
                        data.put(a.toString(), String.format("block=%s u64(le)=0x%016x f32=%s f64=%s",
                            b.getName(), raw, Float.intBitsToFloat((int) raw), Double.longBitsToDouble(raw)));
                    }
                rec.put("referenced_data", data);
                List<String> callees = new ArrayList<>();
                for (Function c : f.getCalledFunctions(monitor)) callees.add(c.getName() + " @ " + c.getEntryPoint() + " :: " + c.getPrototypeString(false, false));
                rec.put("callees", callees);
                List<String> callers = new ArrayList<>();
                for (Function c : f.getCallingFunctions(monitor)) callers.add(c.getName() + " @ " + c.getEntryPoint());
                rec.put("callers", callers);
                DecompileResults r = dec.decompileFunction(f, 60, monitor);
                if (r != null && r.decompileCompleted()) {
                    rec.put("pseudocode", r.getDecompiledFunction().getC());
                    rec.put("error", null);
                } else {
                    rec.put("pseudocode", null);
                    rec.put("error", r == null ? "null result" : r.getErrorMessage());
                }
                w.println(gson.toJson(rec));
            }
        }
        dec.dispose();
    }
}
