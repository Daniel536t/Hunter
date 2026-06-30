import pathlib
f = pathlib.Path.home() / "hunter" / "solve.py"
code = f.read_text()

# Replace the generic feedback line with detailed forge output
old = "feedback = f\"## FORGE OUTPUT:\n{trace[-2000:]}\""
new = """error_class = classify_forge_error(trace)
            hint = ERROR_HINTS.get(error_class, ERROR_HINTS["EXECUTION_FAILURE"])
            compile_errors = [l for l in trace.splitlines() if 'Error' in l]
            if compile_errors:
                log(f"compile errors ({len(compile_errors)}):")
                for ce in compile_errors[-5:]: log(f"  {ce.strip()[:200]}")
            error_history.append(f"[Attempt {i+1}] {error_class}")
            error_context = "\\n".join(error_history[-3:])
            log(f"failed [{error_class}]")
            feedback = f\"\"\"## PREVIOUS ATTEMPTS:
{error_context}

## LATEST FAILURE [{error_class}]:
{hint}

## FORGE OUTPUT:
{trace[-2000:]}\"\"\""""

if old in code: code = code.replace(old, new); f.write_text(code); print("Added error feedback to solve_generic")
else: print("Not found")
