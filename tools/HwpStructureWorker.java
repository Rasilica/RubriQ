import java.io.PrintStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import kr.dogfoot.hwplib.object.HWPFile;
import kr.dogfoot.hwplib.object.bodytext.Section;
import kr.dogfoot.hwplib.object.bodytext.control.Control;
import kr.dogfoot.hwplib.object.bodytext.paragraph.Paragraph;
import kr.dogfoot.hwplib.reader.HWPReader;

public class HwpStructureWorker {
    private static final int LIMIT = 60000;

    private static String quote(String value) {
        StringBuilder escaped = new StringBuilder("\"");
        for (int index = 0; index < value.length(); index++) {
            char character = value.charAt(index);
            if (character == '"' || character == '\\') {
                escaped.append('\\').append(character);
            } else if (character < 32 || Character.isSurrogate(character)) {
                escaped.append(String.format("\\u%04x", (int) character));
            } else {
                escaped.append(character);
            }
            if (escaped.length() > LIMIT) throw new IllegalStateException();
        }
        return escaped.append('"').toString();
    }

    private static String paragraph(Paragraph paragraph, String path) throws Exception {
        String text = paragraph.getNormalString();
        StringBuilder result = new StringBuilder("{\"path\":" + quote(path)
            + ",\"text\":" + quote(text == null ? "" : text) + ",\"controls\":[");
        ArrayList<Control> controls = paragraph.getControlList();
        if (controls != null) {
            if (controls.size() > 1000) throw new IllegalStateException();
            for (int index = 0; index < controls.size(); index++) {
                if (index > 0) result.append(',');
                result.append("{\"path\":").append(quote(path + "/control[" + index + "]"))
                    .append(",\"kind\":").append(quote(controls.get(index).getType().name()))
                    .append('}');
                if (result.length() > LIMIT) throw new IllegalStateException();
            }
        }
        return result.append("]}").toString();
    }

    private static String read(String path) throws Exception {
        HWPFile document = HWPReader.fromFile(path);
        ArrayList<Section> sections = document.getBodyText().getSectionList();
        if (sections.isEmpty() || sections.size() > 1000) throw new IllegalStateException();
        StringBuilder result = new StringBuilder("{\"sections\":[");
        for (int sectionIndex = 0; sectionIndex < sections.size(); sectionIndex++) {
            if (sectionIndex > 0) result.append(',');
            String sectionPath = "BodyText/Section" + sectionIndex;
            Section section = sections.get(sectionIndex);
            if (section.getParagraphCount() > 1000) throw new IllegalStateException();
            result.append("{\"path\":").append(quote(sectionPath)).append(",\"paragraphs\":[");
            for (int index = 0; index < section.getParagraphCount(); index++) {
                if (index > 0) result.append(',');
                result.append(paragraph(section.getParagraph(index), sectionPath + "/paragraph[" + index + "]"));
                if (result.length() > LIMIT) throw new IllegalStateException();
            }
            result.append("]}");
        }
        String json = result.append("]}").toString();
        if (json.getBytes(StandardCharsets.UTF_8).length > LIMIT) throw new IllegalStateException();
        return json;
    }

    public static void main(String[] args) {
        PrintStream output = System.out;
        System.setOut(new PrintStream(java.io.OutputStream.nullOutputStream()));
        System.setErr(new PrintStream(java.io.OutputStream.nullOutputStream()));
        try {
            if (args.length != 1) throw new IllegalArgumentException();
            output.println(read(args[0]));
        } catch (Exception failure) {
            output.println("{\"error\":\"reader_failed\"}");
            System.exit(1);
        }
    }
}
