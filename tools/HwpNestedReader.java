import java.io.OutputStream;
import java.io.PrintStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.util.ArrayList;
import java.util.List;
import kr.dogfoot.hwplib.object.HWPFile;
import kr.dogfoot.hwplib.object.bodytext.ParagraphListInterface;
import kr.dogfoot.hwplib.object.bodytext.control.*;
import kr.dogfoot.hwplib.object.bodytext.control.table.Cell;
import kr.dogfoot.hwplib.object.bodytext.paragraph.Paragraph;
import kr.dogfoot.hwplib.object.bodytext.paragraph.text.*;
import kr.dogfoot.hwplib.reader.HWPReader;

public class HwpNestedReader {
    private static final class OutputLimit extends RuntimeException {}
    private static final int MAX_BLOCKS = 10000;
    private static final int MAX_DEPTH = 64;
    private static final int MAX_BYTES = 4 * 1024 * 1024;
    private final List<String> nodes = new ArrayList<>();
    private final List<String> omitted = new ArrayList<>();
    private final List<String> references = new ArrayList<>();
    private int outputSize = 0;

    private static String quote(String value) {
        if (value == null) return "null";
        StringBuilder escaped = new StringBuilder("\"");
        for (int index = 0; index < value.length(); index++) {
            char ch = value.charAt(index);
            if (ch == '"' || ch == '\\') escaped.append('\\').append(ch);
            else if (ch < 32 || Character.isSurrogate(ch)) {
                escaped.append(String.format("\\u%04x", (int) ch));
            } else escaped.append(ch);
            if (escaped.length() > MAX_BYTES) throw new OutputLimit();
        }
        return escaped.append('"').toString();
    }

    private void add(List<String> target, String value) {
        outputSize += value.getBytes(StandardCharsets.UTF_8).length + 1;
        if (outputSize > MAX_BYTES) throw new OutputLimit();
        target.add(value);
    }

    private void omit(String path) {
        if (omitted.size() >= 20000) throw new IllegalStateException();
        add(omitted, quote(path));
    }

    private boolean room(String path, int depth) {
        if (depth > MAX_DEPTH || nodes.size() >= MAX_BLOCKS) {
            omit(path);
            return false;
        }
        return true;
    }

    private void node(String path, String kind, String text, String parent,
                      Integer fragment, int start) {
        add(nodes, "{\"path\":" + quote(path) + ",\"kind\":" + quote(kind)
            + ",\"text\":" + quote(text) + ",\"parent\":" + quote(parent)
            + ",\"fragment\":" + fragment + ",\"start\":" + start + "}");
    }

    private void paragraphs(ParagraphListInterface list, String path, String parent,
                            int depth) throws Exception {
        for (int index = 0; index < list.getParagraphCount(); index++) {
            String current = path + "/paragraph[" + index + "]";
            if (!room(current, depth)) {
                omit(path);
                return;
            }
            paragraph(list.getParagraph(index), current, parent, depth);
        }
    }

    private void table(ControlTable table, String path, String parent, int depth) throws Exception {
        if (table.getCaption() != null) omit(path);
        for (int row = 0; row < table.getRowList().size(); row++) {
            List<Cell> cells = table.getRowList().get(row).getCellList();
            for (int cell = 0; cell < cells.size(); cell++) {
                String current = path + "/row[" + row + "]/cell[" + cell + "]";
                if (!room(current, depth)) {
                    omit(path);
                    return;
                }
                node(current, "table_cell", "", parent, null, 0);
                paragraphs(cells.get(cell).getParagraphList(), current, current, depth + 1);
            }
        }
    }

    private void story(ParagraphListInterface list, String kind, String path, String parent,
                       String owner, int fragment, int offset, int depth) throws Exception {
        boolean available = room(path, depth);
        add(references, "{\"kind\":" + quote(kind) + ",\"path\":" + quote(path)
            + ",\"owner\":" + quote(owner) + ",\"fragment\":" + fragment
            + ",\"offset\":" + offset + ",\"resolved\":" + available + "}");
        if (!available) return;
        node(path, kind, "", parent, null, 0);
        paragraphs(list, path, path, depth + 1);
    }

    private void control(Control control, String path, String parent, String owner,
                         int fragment, int offset, int depth) throws Exception {
        if (control instanceof ControlTable table) table(table, path, parent, depth);
        else if (control instanceof ControlFootnote note) {
            story(note.getParagraphList(), "footnote", path, parent, owner, fragment, offset, depth);
        } else if (control instanceof ControlHeader header) {
            story(header.getParagraphList(), "header", path, parent, owner, fragment, offset, depth);
        } else if (control instanceof ControlFooter footer) {
            story(footer.getParagraphList(), "footer", path, parent, owner, fragment, offset, depth);
        } else omit(path);
    }

    private static boolean matches(HWPCharControlExtend character, Control control) {
        return switch (control.getType()) {
            case Table -> character.isTable();
            case Footnote -> character.isFootNote();
            case Header -> character.isHeader();
            case Footer -> character.isFooter();
            default -> true;
        };
    }

    private void paragraph(Paragraph paragraph, String path, String parent, int depth)
            throws Exception {
        List<Control> controls = paragraph.getControlList();
        if (controls == null) controls = List.of();
        List<HWPChar> characters = paragraph.getText() == null
            ? List.of() : paragraph.getText().getCharList();
        StringBuilder text = new StringBuilder();
        int controlIndex = 0;
        int fragment = 1;
        int start = 0;
        for (int index = 0; index < characters.size(); index++) {
            HWPChar character = characters.get(index);
            if (character instanceof HWPCharControlExtend extended) {
                if (!room(path, depth)) return;
                String value = text.toString();
                int length = value.codePointCount(0, value.length());
                node(path, "paragraph", value, parent, fragment, start);
                text.setLength(0);
                String controlPath = path + "/control[" + controlIndex + "]";
                if (controlIndex >= controls.size() || !matches(extended, controls.get(controlIndex))) {
                    omit(controlPath);
                } else {
                    control(controls.get(controlIndex), controlPath, parent, path,
                        fragment, length, depth + 1);
                }
                controlIndex++;
                fragment++;
                start += length;
            } else if (character.getType() == HWPCharType.Normal) {
                text.append((char) character.getCode());
            } else if (character.getCode() == 9) text.append('\t');
            else if (character.getCode() == 10) text.append('\n');
            else if (character.getCode() == 30) text.append('\u00a0');
            else if (character.getCode() == 31) text.append('\u2007');
            else if (character.getCode() != 13) omit(path + "/char[" + index + "]");
            if (text.length() > MAX_BYTES) throw new OutputLimit();
        }
        if (room(path, depth)) node(path, "paragraph", text.toString(), parent, fragment, start);
        for (; controlIndex < controls.size(); controlIndex++) {
            omit(path + "/control[" + controlIndex + "]");
        }
    }

    private String read(String input) throws Exception {
        HWPFile document = HWPReader.fromFile(input);
        var sections = document.getBodyText().getSectionList();
        if (sections.isEmpty() || sections.size() > 1000) throw new IllegalStateException();
        List<String> parts = new ArrayList<>();
        for (int index = 0; index < sections.size(); index++) {
            String path = "BodyText/Section" + index;
            parts.add(quote(path));
            paragraphs(sections.get(index), path, null, 0);
        }
        String json = "{\"parts\":[" + String.join(",", parts) + "],\"nodes\":["
            + String.join(",", nodes) + "],\"omitted\":[" + String.join(",", omitted)
            + "],\"references\":[" + String.join(",", references) + "]}";
        if (json.getBytes(StandardCharsets.UTF_8).length > MAX_BYTES) throw new OutputLimit();
        return json;
    }

    public static void main(String[] args) {
        PrintStream output = System.out;
        System.setOut(new PrintStream(OutputStream.nullOutputStream()));
        System.setErr(new PrintStream(OutputStream.nullOutputStream()));
        try {
            if (args.length != 2) throw new IllegalArgumentException();
            String json = new HwpNestedReader().read(args[0]);
            Files.writeString(Path.of(args[1]), json, StandardCharsets.UTF_8,
                StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE);
            output.println("ok");
        } catch (OutputLimit failure) {
            output.println("output_limit");
        } catch (Exception failure) {
            output.println("reader_failed");
            System.exit(1);
        }
    }
}
