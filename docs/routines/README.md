# Routine Documentation

Documentation for Condor routines.

## Available Documentation

### validate_setup
- **VALIDATE_SETUP_USAGE.md** - How to use the validate_setup routine from agents

## Adding New Documentation

When creating a new routine, document:
1. Purpose and use case
2. Required config parameters
3. Response structure
4. Example usage from agents
5. Common pitfalls or edge cases

## Documentation Template

```markdown
# {Routine Name}

## Purpose
Brief description of what this routine does.

## Configuration

### Required Parameters
- `param1`: Description
- `param2`: Description

### Optional Parameters
- `param3`: Description (default: value)

## Response Structure

### Success Response
```json
{
  "field1": "value",
  "field2": 123
}
```

### Error Response
Returns string error message.

## Usage from Agent

\```python
result = manage_routines(
    action="run",
    name="routine_name",
    config={
        "param1": value1,
        "param2": value2,
    }
)
\```

## Examples

### Example 1: Basic Usage
[Description and code]

### Example 2: Advanced Usage
[Description and code]

## Notes
Any caveats, performance considerations, or tips.
```
